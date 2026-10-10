"""Server-side YouTube show-note processing via ordinary POST /urls ingestion."""

import logging

import pytest

from ref_api import service
from ref_cli import youtube_extract

VIDEO_ID = "zmrPY6S1FwY"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


@pytest.fixture
def capture(monkeypatch, tmp_path):
    """Capture API processing without touching the live references archive."""
    seen = []
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(tmp_path / "references.md"))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: False)

    def record(url, force):
        seen.append(url)
        print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", record)
    return seen


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
    assert capture == [
        VIDEO_URL, "https://example.org/resource", "https://github.com/example/code"
    ]
    assert "found=2" in result.output
    assert "timestamps_ignored=2" in result.output
    assert "YouTube notes: metadata" in caplog.text
    assert "status=added url=https://example.org/resource" in caplog.text
    assert "YouTube notes: complete" in caplog.text


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
    assert capture == [VIDEO_URL, "https://example.com/out"]


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
    assert calls == [VIDEO_ID]
    assert capture == [
        VIDEO_URL, f"https://www.youtube.com/watch?v={another_video}"
    ]


def test_metadata_failure_does_not_lose_parent(capture, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise RuntimeError("YouTube metadata blocked")

    monkeypatch.setattr(youtube_extract, "read_video_card", unavailable)
    with caplog.at_level(logging.WARNING, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)

    assert result.status == "added"
    assert capture == [VIDEO_URL]
    assert "YouTube notes: unavailable" in result.output
    assert "YouTube metadata blocked" in caplog.text


def test_nonyoutube_urls_do_not_scan_notes(capture, monkeypatch):
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: pytest.fail("show note fetch for non-YouTube URL"),
    )
    result = service.process_one("https://example.com/article")
    assert result.status == "added"
    assert capture == ["https://example.com/article"]


def test_api_skips_no_scan(capture, monkeypatch):
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: True)
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: pytest.fail("skip pattern ignored"),
    )
    result = service.process_one(VIDEO_URL)
    assert result.status == "skipped"
    assert capture == []


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
    with caplog.at_level(logging.WARNING, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)

    assert capture == [VIDEO_URL, "https://example.org/a", "https://example.org/b"]
    assert "found=3" in result.output
    assert "scanned=2" in result.output
    assert "YouTube notes: capped" in caplog.text


def test_failed_outbound_link_does_not_abort_other_links(capture, monkeypatch, caplog):
    monkeypatch.setattr(
        youtube_extract, "read_video_card",
        lambda *a, **k: {
            "description": "https://example.org/a\nhttps://example.org/b",
        },
    )
    def record(url, force):
        capture.append(url)
        if url == "https://example.org/a":
            print("Error: denied")
        else:
            print(f"2026-10-10T12:00:00|[{url}]|(Example)|General|General")

    monkeypatch.setattr(service.ref_cli, "process_url", record)
    with caplog.at_level(logging.WARNING, logger="ref_api.service"):
        result = service.process_one(VIDEO_URL)

    assert result.status == "added"
    assert capture == [VIDEO_URL, "https://example.org/a", "https://example.org/b"]
    assert "errors=1" in result.output
    assert "status=error" in caplog.text
