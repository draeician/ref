"""Regression tests for automatic YouTube show-note discovery via ref-api."""

from __future__ import annotations

import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from ref_api import service
from ref_api.app import create_app
from ref_api.schemas import UrlResult

VIDEO_ID = "zmrPY6S1FwY"
PARENT = f"https://www.youtube.com/watch?v={VIDEO_ID}"


def _stub_ingest(monkeypatch):
    calls = []

    def process_one(url, force=False):
        calls.append((url, force))
        return UrlResult(
            input=url,
            url=url,
            status="added",
            output=f"recorded|{url}",
        )

    monkeypatch.setattr(service, "process_one", process_one)
    return calls


def _card(description):
    return {
        "title": "Video with show notes",
        "source": "youtube_api",
        "description": description,
        "links": {},
    }


def test_auto_processes_show_note_links_through_process_one(monkeypatch, tmp_path, caplog):
    calls = _stub_ingest(monkeypatch)
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(tmp_path / "references.md"))
    saved = []

    def read_card(video_id, base):
        saved.append((video_id, base))
        return _card(
            "https://github.com/example/project\n"
            "https://example.org/article\n"
            "https://example.org/article\n"
            "http://127.0.0.1/private\n"
            f"{PARENT}\n"
        )

    monkeypatch.setattr(service, "read_video_card", read_card)
    with caplog.at_level(logging.INFO):
        results = service.process_many([PARENT])

    assert [u for u, _ in calls] == [
        PARENT, "https://github.com/example/project",
        "https://example.org/article",
    ]
    assert saved == [(VIDEO_ID, str(tmp_path))]
    assert [r.status for r in results] == ["added", "added", "added"]
    assert results[0].discovered_from is None
    assert [r.discovered_from for r in results[1:]] == [PARENT, PARENT]
    assert "description_chars=" in caplog.text
    assert "links_found=2" in caplog.text
    assert "result status=added" in caplog.text


def test_existing_parent_still_scans(monkeypatch):
    seen = []

    def fake_process(url, force=False):
        seen.append(url)
        return UrlResult(input=url, url=url, status="exists" if url == PARENT else "added")

    monkeypatch.setattr(service, "process_one", fake_process)
    monkeypatch.setattr(service, "read_video_card", lambda *args: _card("https://example.com/one"))
    result = service.process_many([PARENT])
    assert seen == [PARENT, "https://example.com/one"]
    assert [r.status for r in result] == ["exists", "added"]


def test_parent_failure_does_not_scan(monkeypatch):
    calls = []

    def failed(url, force=False):
        calls.append(url)
        return UrlResult(input=url, url=url, status="error", message="video unavailable")

    monkeypatch.setattr(service, "process_one", failed)
    monkeypatch.setattr(
        service, "read_video_card",
        lambda *args: (_ for _ in ()).throw(AssertionError("should not read")),
    )
    results = service.process_many([PARENT])
    assert len(results) == 1
    assert calls == [PARENT]


def test_metadata_unavailable_does_not_fail_video(monkeypatch, caplog):
    calls = _stub_ingest(monkeypatch)

    def unavailable(*args):
        raise RuntimeError("YouTube rate limited")

    monkeypatch.setattr(service, "read_video_card", unavailable)
    with caplog.at_level(logging.WARNING):
        results = service.process_many([PARENT])
    assert len(results) == 1
    assert calls == [(PARENT, False)]
    assert "metadata unavailable" in caplog.text


def test_youtube_children_are_not_recursively_scanned(monkeypatch):
    other = "https://www.youtube.com/watch?v=abcdefghijk"
    calls = _stub_ingest(monkeypatch)
    read_count = []

    def card_for(video_id, base):
        read_count.append(video_id)
        return _card(other)

    monkeypatch.setattr(service, "read_video_card", card_for)
    results = service.process_many([PARENT])
    assert [url for url, _ in calls] == [PARENT, other]
    assert read_count == [VIDEO_ID]
    assert results[1].discovered_from == PARENT


def test_auto_discovery_deduplicates_across_explicit_batch(monkeypatch):
    link = "https://example.org/same"
    calls = _stub_ingest(monkeypatch)
    monkeypatch.setattr(service, "read_video_card", lambda *args: _card(link))
    results = service.process_many([PARENT, link])
    assert [url for url, _ in calls] == [PARENT, link]
    assert all(r.discovered_from is None for r in results)


def test_child_failure_reported_and_next_child_continues(monkeypatch, caplog):
    calls = []

    def fake(url, force=False):
        calls.append(url)
        status = "error" if url == "https://example.org/bad" else "added"
        return UrlResult(input=url, url=url, status=status, message=status)

    monkeypatch.setattr(service, "process_one", fake)
    monkeypatch.setattr(
        service, "read_video_card",
        lambda *args: _card("https://example.org/bad https://example.org/good"),
    )
    with caplog.at_level(logging.INFO):
        results = service.process_many([PARENT])
    assert calls == [PARENT, "https://example.org/bad", "https://example.org/good"]
    assert [r.status for r in results] == ["added", "error", "added"]
    assert "result status=error" in caplog.text


def test_auto_discovery_is_bounded(monkeypatch, caplog):
    calls = _stub_ingest(monkeypatch)
    notes = " ".join(f"https://example.org/link-{n}" for n in range(46))
    monkeypatch.setattr(service, "read_video_card", lambda *args: _card(notes))
    with caplog.at_level(logging.WARNING):
        results = service.process_many([PARENT])
    assert len(calls) == service.MAX_YOUTUBE_SHOW_NOTE_LINKS + 1
    assert len(results) == service.MAX_YOUTUBE_SHOW_NOTE_LINKS + 1
    assert "omitted 6 links" in caplog.text


def test_non_youtube_requests_do_not_scan(monkeypatch):
    calls = _stub_ingest(monkeypatch)
    monkeypatch.setattr(
        service, "read_video_card",
        lambda *args: (_ for _ in ()).throw(AssertionError("not YouTube")),
    )
    assert len(service.process_many(["https://example.com/post"])) == 1
    assert calls == [("https://example.com/post", False)]


def test_post_urls_response_includes_auto_discovered_links(monkeypatch):
    calls = _stub_ingest(monkeypatch)
    monkeypatch.setattr(
        service, "read_video_card", lambda *args: _card("https://example.org/resource")
    )
    with patch("ref_api.app._bootstrap_archive"):
        with TestClient(create_app()) as client:
            response = client.post("/urls", json={"url": PARENT})
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["url"] for r in results] == [PARENT, "https://example.org/resource"]
    assert results[0]["discovered_from"] is None
    assert results[1]["discovered_from"] == PARENT
    assert calls == [(PARENT, False), ("https://example.org/resource", False)]
