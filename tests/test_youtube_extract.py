"""Offline tests for YouTube show-note discovery and ref-api submission."""

from types import SimpleNamespace

from ref_cli import youtube_extract as yt

VIDEO = "dQw4w9WgXcQ"


def card(notes=""):
    return {
        "video_id": VIDEO, "title": "Demo", "description": notes,
        "channel_title": "Channel", "links": {},
    }


def test_video_hosts_and_shapes():
    assert yt.youtube_video_id(f"https://youtu.be/{VIDEO}") == VIDEO
    assert yt.youtube_video_id(f"https://www.youtube.com/watch?v={VIDEO}") == VIDEO
    assert yt.youtube_video_id(f"https://youtube.com/shorts/{VIDEO}") == VIDEO
    assert yt.youtube_video_id(f"https://youtube.com.evil.example/watch?v={VIDEO}") is None
    assert yt.youtube_video_id("https://youtube.com/playlist?list=PL1234") is None


def test_extract_notes_filters_self_and_local_links():
    notes = (
        "0:00 Introduction\n1:20 - Demo\n"
        "https://github.com/team/tool\nhttps://example.com/guide\n"
        "https://github.com/team/tool\n"
        f"https://youtu.be/{VIDEO}\n"
        "http://127.0.0.1/admin\nhttps://localhost/private"
    )
    assert yt.chapters_from_description(notes) == [
        ("0:00", "Introduction"), ("1:20", "Demo")
    ]
    assert yt.outbound_urls(card(notes), VIDEO) == [
        "https://github.com/team/tool", "https://example.com/guide"
    ]


def test_card_cache_is_used(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "load_video_card", lambda *args: card("cached"))
    monkeypatch.setattr(
        yt, "fetch_youtube_video",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("fetch called"))
    )
    assert yt.read_video_card(VIDEO, str(tmp_path))["description"] == "cached"


def test_default_scan_deduplicates_videos(monkeypatch):
    rows = [
        SimpleNamespace(url=f"https://youtu.be/{VIDEO}"),
        SimpleNamespace(url="https://example.com"),
        SimpleNamespace(url=f"https://www.youtube.com/watch?v={VIDEO}"),
    ]
    monkeypatch.setattr(yt, "iter_data_rows", lambda path: rows)
    assert yt._source_urls([], "references.md", None) == [rows[0].url]


def test_dry_run_never_sends_to_api(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(yt, "_default_file", lambda: str(tmp_path / "refs.md"))
    monkeypatch.setattr(yt, "read_video_card", lambda *a, **kw: card("https://example.org/link"))
    monkeypatch.setattr(
        yt, "ingest_urls",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("API called"))
    )
    assert yt.main([f"https://youtu.be/{VIDEO}"]) == 0
    output = capsys.readouterr().out
    assert "Show notes:" in output
    assert "https://example.org/link" in output


def test_apply_requires_api(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "_default_file", lambda: str(tmp_path / "refs.md"))
    monkeypatch.setattr("ref_cli.cli.load_config", lambda: {})
    monkeypatch.setattr(yt, "get_api_base_url", lambda config: None)
    assert yt.main(["--apply", f"https://youtu.be/{VIDEO}"]) == 1


def test_apply_sends_parent_and_links_to_api(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "_default_file", lambda: str(tmp_path / "refs.md"))
    monkeypatch.setattr("ref_cli.cli.load_config", lambda: {"api_url": "http://archive:8000"})
    monkeypatch.setattr(yt, "read_video_card", lambda *a, **kw: card(
        "https://github.com/team/tool\nhttps://example.org/guide"
    ))
    sent = []

    def ingest(base_url, **kwargs):
        sent.append((base_url, kwargs["url_value"]))
        return [{"status": "added"}]

    monkeypatch.setattr(yt, "ingest_urls", ingest)
    assert yt.main(["--apply", f"https://youtu.be/{VIDEO}"]) == 0
    assert sent == [
        ("http://archive:8000", f"https://www.youtube.com/watch?v={VIDEO}"),
        ("http://archive:8000", "https://github.com/team/tool"),
        ("http://archive:8000", "https://example.org/guide"),
    ]


def test_apply_still_records_parent_when_metadata_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(yt, "_default_file", lambda: str(tmp_path / "refs.md"))
    monkeypatch.setattr("ref_cli.cli.load_config", lambda: {"api_url": "http://archive:8000"})
    monkeypatch.setattr(yt, "read_video_card", lambda *a, **kw: 1 / 0)
    sent = []

    def ingest(base_url, **kwargs):
        sent.append(kwargs["url_value"])
        return [{"status": "added"}]

    monkeypatch.setattr(yt, "ingest_urls", ingest)
    assert yt.main(["--apply", f"https://youtu.be/{VIDEO}"]) == 1
    assert sent == [f"https://www.youtube.com/watch?v={VIDEO}"]
