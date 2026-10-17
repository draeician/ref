"""Deterministic regression tests for the show-note background worker.

These cover the issue #18 contract: the parent response is no longer hostage to
slow discovery or child processing, a slow worker child does not block a *new*
independent ingest, discovered playlists do not expand, direct playlists still
do, duplicate submissions do not double-fan-out, accepted jobs survive a restart,
and worker lifecycle cannot spawn overlapping workers.
"""

from __future__ import annotations

import threading
import time

import pytest

from ref_api import service
from ref_cli import youtube_extract

VIDEO_ID = "zmrPY6S1FwY"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLabcdefghij"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point the service at an isolated archive path (no live references.md)."""
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(tmp_path / "references.md"))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: False)
    return tmp_path


def _ingest_urls(queue):
    return [job["url"] for job in queue.jobs() if job["kind"] == "ingest"]


def test_parent_returns_before_slow_discovery(isolated, monkeypatch):
    """Discovery (card fetch) runs on the worker, not on the parent request path."""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from ref_api.app import create_app

    release = threading.Event()
    discovery_started = threading.Event()

    def slow_card(video_id, base):
        discovery_started.set()
        release.wait(timeout=15)
        return {"description": "https://example.org/slow", "source": "cache"}

    monkeypatch.setattr(youtube_extract, "read_video_card", slow_card)
    monkeypatch.setattr(
        service.ref_cli, "process_url",
        lambda url, force: print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General"),
    )

    try:
        with patch("ref_api.app._bootstrap_archive"):
            with TestClient(create_app()) as client:
                response = client.post("/urls", json={"url": VIDEO_URL})

                assert response.status_code == 200
                result = response.json()["results"][0]
                assert result["status"] == "added"
                # Discovery is off the request path.
                assert "discovery queued" in result["output"]
                assert "found=" not in result["output"]

                # The worker is now blocked inside discovery; parent already returned.
                assert discovery_started.wait(timeout=5)
                release.set()
    finally:
        release.set()


def test_worker_slow_child_does_not_block_new_ingest(isolated, monkeypatch):
    """A worker stuck in slow child work must not delay a new independent ingest."""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from ref_api.app import create_app

    slow_url = "https://example.org/slow"
    other_url = "https://example.org/other"
    release = threading.Event()
    slow_started = threading.Event()

    def fake_process(url, force):
        if url == slow_url:
            slow_started.set()
            release.wait(timeout=20)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)

    try:
        with patch("ref_api.app._bootstrap_archive"):
            with TestClient(create_app()) as client:
                service._get_queue().enqueue(slow_url)
                assert slow_started.wait(timeout=5)

                started = time.monotonic()
                response = client.post("/urls", json={"url": other_url})
                elapsed = time.monotonic() - started

                assert response.status_code == 200
                assert response.json()["results"][0]["status"] == "added"
                assert elapsed < 5  # did not wait on the blocked worker child
                release.set()
    finally:
        release.set()


def test_discovered_playlist_child_is_not_expanded(isolated, monkeypatch):
    calls = []

    def fake_record_link(url, force):
        calls.append(("record_link", url))
        print(f"2026-10-10T12:00:00|[{url}]|(Playlist)|Channel|YouTube")

    monkeypatch.setattr(service.ref_cli, "record_youtube_playlist_link", fake_record_link)
    monkeypatch.setattr(
        service.ref_cli, "process_url",
        lambda url, force: calls.append(("process_url", url)),
    )

    result = service.process_one(
        PLAYLIST_URL,
        _discover_youtube_links=False,
        _suppress_playlist_expansion=True,
    )

    assert result.status == "added"
    assert calls == [("record_link", PLAYLIST_URL)]


def test_direct_playlist_still_uses_full_processing(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(
        service.ref_cli, "process_url",
        lambda url, force: calls.append(("process_url", url)),
    )
    monkeypatch.setattr(
        service.ref_cli, "record_youtube_playlist_link",
        lambda url, force: calls.append(("record_link", url)),
    )

    service.process_one(PLAYLIST_URL)

    assert ("process_url", PLAYLIST_URL) in calls
    assert ("record_link", PLAYLIST_URL) not in calls


def test_repeated_parent_submission_no_double_fanout(isolated, monkeypatch):
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": "https://example.org/a\nhttps://example.org/b",
            "source": "cache",
        },
    )

    seen = set()

    def fake_process(url, force):
        if url in seen:
            print(f"URL {url} already recorded.")
        else:
            seen.add(url)
            print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)

    first = service.process_one(VIDEO_URL)
    second = service.process_one(VIDEO_URL)

    assert first.status == "added"
    assert second.status == "exists"

    # Discovery is deduplicated: a single discover job fans out once.
    queue = service._get_queue()
    assert service._drain_show_notes_queue(queue) is True
    assert _ingest_urls(queue) == ["https://example.org/a", "https://example.org/b"]


def test_worker_drains_child_and_marks_done(isolated, monkeypatch):
    processed = []

    def fake_process(url, force):
        processed.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)

    queue = service._get_queue()
    queue.enqueue("https://example.org/a", parent_video_id=VIDEO_ID)
    assert service._drain_show_notes_queue(queue) is True
    assert processed == ["https://example.org/a"]
    assert queue.stats()["done"] == 1
    assert service._drain_show_notes_queue(queue) is False


def test_worker_retries_failed_child_then_terminal(isolated, monkeypatch):
    import ref_api.show_notes_queue as sq

    def failing(url, force):
        print("Error: denied")

    monkeypatch.setattr(service.ref_cli, "process_url", failing)
    monkeypatch.setattr(sq, "RETRY_BASE_DELAY_SECONDS", 0.0)

    queue = service._get_queue()
    queue.enqueue("https://example.org/a")
    for _ in range(sq.MAX_ATTEMPTS):
        assert service._drain_show_notes_queue(queue) is True
    assert queue.stats()["failed"] == 1
    assert service._drain_show_notes_queue(queue) is False


def test_restart_recovery_then_worker_drains(isolated, monkeypatch):
    processed = []

    def fake_process(url, force):
        processed.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {"description": "https://example.org/a", "source": "cache"},
    )

    # Parent enqueues a discovery job durably.
    service.process_one(VIDEO_URL)
    assert service._get_queue().unfinished_count() == 1

    # Simulate a process restart: drop in-memory state and rebuild from disk.
    service._queue = None
    service._queue_dir = None
    queue = service._get_queue()
    queue.recover()

    assert service._drain_show_notes_queue(queue) is True  # discover -> enqueue child
    assert processed == [VIDEO_URL]  # discovery does not record; only parent so far
    assert service._drain_show_notes_queue(queue) is True  # child ingest
    assert processed == [VIDEO_URL, "https://example.org/a"]
    assert queue.stats()["done"] == 2


def test_queue_status_endpoint(isolated, monkeypatch):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from ref_api.app import create_app

    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {"description": "https://example.org/a", "source": "cache"},
    )
    monkeypatch.setattr(
        service.ref_cli, "process_url",
        lambda url, force: print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General"),
    )

    with patch("ref_api.app._bootstrap_archive"):
        with TestClient(create_app()) as client:
            client.post("/urls", json={"url": VIDEO_URL})
            response = client.get("/queue")

    assert response.status_code == 200
    body = response.json()
    assert body["unfinished"] >= 1
    assert body["corrupt"] == 0


def test_worker_resumes_after_timed_out_stop_and_restart(isolated, monkeypatch):
    """A timed-out stop + in-process restart must neither overlap workers nor
    leave the queue idle: the exiting worker hands off to a successor."""
    slow_url = "https://example.org/slow"
    other_url = "https://example.org/other"
    release = threading.Event()
    slow_started = threading.Event()
    processed = []

    def fake_process(url, force):
        if url == slow_url:
            slow_started.set()
            release.wait(timeout=20)
        processed.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)

    original_stop = service._ShowNotesWorker.stop

    def fast_stop(self, timeout=0.1):
        return original_stop(self, timeout)

    monkeypatch.setattr(service._ShowNotesWorker, "stop", fast_stop)

    service._worker = None
    try:
        service.start_show_notes_worker()
        first_worker = service._worker
        service._get_queue().enqueue(slow_url)
        assert slow_started.wait(timeout=5)

        # stop times out (worker stuck in slow child); reference is retained.
        service.stop_show_notes_worker()
        assert service._worker is first_worker
        assert service._worker.is_alive()

        # In-process restart while draining must NOT spawn a duplicate worker.
        service.start_show_notes_worker()
        worker_threads = [
            t for t in threading.enumerate() if t.name == "ref-show-notes-worker"
        ]
        assert len(worker_threads) == 1

        # Release the slow child; the old worker finishes, exits, and hands off.
        release.set()
        first_worker._thread.join(timeout=10)
        assert not first_worker.is_alive()

        # A successor worker has taken over and must be the only one running.
        deadline = time.time() + 5
        while time.time() < deadline:
            successor = service._worker
            if successor is not None and successor is not first_worker and successor.is_alive():
                break
            time.sleep(0.05)
        assert service._worker is not None
        assert service._worker is not first_worker
        assert service._worker.is_alive()

        worker_threads = [
            t for t in threading.enumerate() if t.name == "ref-show-notes-worker"
        ]
        assert len(worker_threads) == 1

        # The successor resumes draining: a newly queued job is processed.
        service._get_queue().enqueue(other_url)
        deadline = time.time() + 5
        while other_url not in processed and time.time() < deadline:
            time.sleep(0.05)
        assert other_url in processed
    finally:
        release.set()
        service.stop_show_notes_worker()
        worker = service._worker
        if worker is not None:
            worker._thread.join(timeout=5)
        service._worker = None
