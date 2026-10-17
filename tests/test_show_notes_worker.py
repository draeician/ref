"""Deterministic regression tests for the show-note background worker.

These cover the issue #18 contract: the parent response is no longer hostage to
slow child processing, discovered playlists do not expand, direct playlists still
do, duplicate submissions do not double-fan-out, and accepted jobs survive a
restart and are retried with bounded backoff.
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


def test_parent_returns_before_slow_child_released(isolated, monkeypatch):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from ref_api.app import create_app

    child_url = "https://example.org/slow"
    release = threading.Event()
    child_started = threading.Event()
    processed = []

    def fake_process(url, force):
        if url == child_url:
            child_started.set()
            release.wait(timeout=15)
        processed.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {"description": child_url, "source": "cache"},
    )

    try:
        with patch("ref_api.app._bootstrap_archive"):
            with TestClient(create_app()) as client:
                response = client.post("/urls", json={"url": VIDEO_URL})

                # The parent response returns promptly and truthfully reports
                # queued (not completed) children.
                assert response.status_code == 200
                result = response.json()["results"][0]
                assert result["status"] == "added"
                assert "queued=1" in result["output"]
                assert "queue_unfinished=1" in result["output"]

                # The worker has claimed the slow child and is blocked on it, but
                # the child is not yet recorded.
                assert child_started.wait(timeout=5)
                assert child_url not in processed

                release.set()
                deadline = time.time() + 5
                while child_url not in processed and time.time() < deadline:
                    time.sleep(0.05)
                assert child_url in processed
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
    queued = [job["url"] for job in service._get_queue().jobs()]
    assert queued == ["https://example.org/a", "https://example.org/b"]


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

    # Parent enqueues the child durably.
    service.process_one(VIDEO_URL)
    assert service._get_queue().unfinished_count() == 1

    # Simulate a process restart: drop in-memory state and rebuild from disk.
    service._queue = None
    service._queue_dir = None
    queue = service._get_queue()
    queue.recover()

    assert service._drain_show_notes_queue(queue) is True
    assert "https://example.org/a" in processed
    assert queue.stats()["done"] == 1


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
    assert body["pending"] == 1
    assert body["unfinished"] == 1
