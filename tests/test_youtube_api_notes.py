"""Server-side YouTube show-note discovery is now fully asynchronous.

A YouTube parent's ``POST /urls`` (or ``process_one``) records the parent and
*enqueues a background ``discover`` job*. The worker then fetches the video card,
extracts outbound links, and enqueues ``ingest`` jobs for each child. These tests
verify both halves: the parent returns without doing discovery, and discovery
(chapter filtering, dedup, capping, no recursive scan) is correct when drained.
"""

import logging

import pytest

from ref_api import service
from ref_cli import youtube_extract

VIDEO_ID = "zmrPY6S1FwY"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.fixture
def capture(monkeypatch, tmp_path):
    """Capture parent process_url calls without touching the live archive."""
    seen = []
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(tmp_path / "references.md"))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: False)

    def record(url, force):
        seen.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", record)
    return seen


def queued_ingest_urls():
    """Return the URLs of all pending/done child (ingest) jobs in the queue."""
    return [job["url"] for job in service._get_queue().jobs() if job["kind"] == "ingest"]


def drain_all(queue):
    """Drain the queue (discover then children) until no runnable job remains."""
    for _ in range(50):
        if not service._drain_show_notes_queue(queue):
            break


def test_normal_api_ingest_discovers_links_but_ignores_chapters(
    capture, monkeypatch, caplog
):
    description = (
        "0:00 Intro\n02:30 Related resources\n"
        "https://example.org/resource\nhttps://github.com/example/code\n"
        f"https://youtu.be/{VIDEO_ID}?t=150\n"
        "https://example.org/resource\n"
    )
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *args, **kwargs: {"description": description, "source": "cache"},
    )

    with caplog.at_level(logging.INFO, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)
        assert result.status == "added"
        # Only the parent is recorded synchronously; discovery is deferred.
        assert capture == [VIDEO_URL]
        assert "discovery queued" in result.output
        assert queued_ingest_urls() == []
        drain_all(service._get_queue())

    assert queued_ingest_urls() == [
        "https://example.org/resource", "https://github.com/example/code"
    ]
    assert "found=2" in caplog.text
    assert "queued=2" in caplog.text
    assert "timestamps_ignored=2" in caplog.text
    assert "YouTube notes: metadata" in caplog.text
    assert "YouTube notes: discovery queued video_id=" + VIDEO_ID in caplog.text
    assert "YouTube notes: discovered" in caplog.text


def test_existing_video_still_checks_links(capture, monkeypatch):
    def exists(url, force):
        capture.append(url)
        print(f"URL {url} already recorded.")

    monkeypatch.setattr(service.ref_cli, "process_url", exists)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *args, **kwargs: {
            "description": "https://example.com/out",
            "source": "cache",
        },
    )
    result = service.process_one(VIDEO_URL)
    assert result.status == "exists"
    assert capture == [VIDEO_URL]
    assert "discovery queued" in result.output
    drain_all(service._get_queue())
    assert queued_ingest_urls() == ["https://example.com/out"]


def test_linked_youtube_videos_do_not_scan_recursively(capture, monkeypatch):
    another_video = "dQw4w9WgXcQ"
    calls = []

    def get_card(video_id, base):
        calls.append(video_id)
        return {
            "description": f"https://www.youtube.com/watch?v={another_video}",
            "source": "cache",
        }

    monkeypatch.setattr(youtube_extract, "read_video_card", get_card)
    result = service.process_one(VIDEO_URL)
    assert result.status == "added"
    assert capture == [VIDEO_URL]
    drain_all(service._get_queue())
    # Only the parent is discovered; the linked video is enqueued as a child,
    # not scanned recursively.
    assert calls == [VIDEO_ID]
    assert queued_ingest_urls() == [f"https://www.youtube.com/watch?v={another_video}"]


def test_metadata_failure_does_not_lose_parent(capture, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise RuntimeError("YouTube metadata blocked")

    monkeypatch.setattr(youtube_extract, "read_video_card", unavailable)
    with caplog.at_level(logging.WARNING, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)
        assert result.status == "added"
        assert capture == [VIDEO_URL]
        # Discovery is deferred; the parent result does not carry the failure.
        assert "discovery queued" in result.output
        drain_all(service._get_queue())

    assert queued_ingest_urls() == []
    assert "YouTube metadata blocked" in caplog.text


def test_nonyoutube_urls_do_not_scan_notes(capture, monkeypatch):
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: pytest.fail("show note fetch for non-YouTube URL"),
    )
    result = service.process_one("https://example.com/article")
    assert result.status == "added"
    assert capture == ["https://example.com/article"]
    assert service._get_queue().jobs() == []


def test_api_skips_no_scan(capture, monkeypatch):
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: True)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: pytest.fail("skip pattern ignored"),
    )
    result = service.process_one(VIDEO_URL)
    assert result.status == "skipped"
    assert capture == []
    assert service._get_queue().jobs() == []


def test_many_links_bounded_and_logged(capture, monkeypatch, caplog):
    monkeypatch.setattr(service, "MAX_YOUTUBE_SHOW_NOTE_LINKS", 2)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": (
                "https://example.org/a\nhttps://example.org/b\n"
                "https://example.org/c"
            ),
        },
    )
    with caplog.at_level(logging.INFO, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)
        assert capture == [VIDEO_URL]  # only the parent recorded synchronously
        drain_all(service._get_queue())

    assert queued_ingest_urls() == ["https://example.org/a", "https://example.org/b"]
    assert "found=3" in caplog.text
    assert "scanned=2" in caplog.text
    assert "queued=2" in caplog.text
    assert "YouTube notes: capped" in caplog.text


def test_duplicate_discovered_links_enqueued_once(capture, monkeypatch):
    """The same discovered URL must not be enqueued twice for one parent."""
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": (
                "https://example.org/a\nhttps://example.org/a\n"
                "https://example.org/a"
            ),
        },
    )
    result = service.process_one(VIDEO_URL)
    assert result.status == "added"
    assert capture == [VIDEO_URL]
    drain_all(service._get_queue())
    assert queued_ingest_urls() == ["https://example.org/a"]


def test_post_urls_endpoint_automatically_enqueues_show_note_links(
    capture, monkeypatch
):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from ref_api.app import create_app

    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": "0:00 Intro\nhttps://example.org/show-notes",
            "source": "cache",
        },
    )
    # Disable the auto-worker so draining is fully deterministic.
    monkeypatch.setattr(service, "start_show_notes_worker", lambda: None)
    with patch("ref_api.app._bootstrap_archive"):
        with TestClient(create_app()) as client:
            response = client.post("/urls", json={"url": VIDEO_URL})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "added"
    assert "discovery queued" in result["output"]
    assert capture == [VIDEO_URL]

    drain_all(service._get_queue())
    assert queued_ingest_urls() == ["https://example.org/show-notes"]


def test_timestamp_only_description_does_not_ingest_children(capture, monkeypatch, caplog):
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": "0:00 Introduction\n01:42 Demo\n1:02:15 Conclusion",
        },
    )
    with caplog.at_level(logging.INFO, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)
        drain_all(service._get_queue())

    assert capture == [VIDEO_URL]
    assert queued_ingest_urls() == []
    assert "found=0" in caplog.text
    assert "timestamps_ignored=3" in caplog.text


def test_info_progress_logs_when_root_is_warning(capture, monkeypatch):
    """Production Uvicorn can leave root at WARNING while we need INFO notes."""
    import io

    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": "https://example.org/guide",
            "source": "cache",
        },
    )
    root = logging.getLogger()
    previous_level = root.level
    sink = io.StringIO()
    handler = logging.StreamHandler(sink)
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    try:
        result = service.process_one(VIDEO_URL)
        drain_all(service._get_queue())
    finally:
        root.setLevel(previous_level)
        root.removeHandler(handler)
        handler.close()

    assert result.status == "added"
    output = sink.getvalue()
    assert "YouTube notes: discovery queued video_id=" + VIDEO_ID in output
    assert "YouTube notes: metadata video_id=" + VIDEO_ID in output
    assert "YouTube notes: discovered" in output
