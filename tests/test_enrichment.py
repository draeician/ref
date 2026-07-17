"""Tests for enrichment helpers (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from ref_cli.enrichment import (
    VideoEnrichment,
    ensure_enrichment_dirs,
    extract_links,
    extract_youtube_video_id,
    infer_role,
    save_video_card,
    update_channel_card,
    video_card_path,
)


def test_extract_youtube_video_id() -> None:
    assert extract_youtube_video_id(
        "https://www.youtube.com/watch?v=XCUWrrmaNck"
    ) == "XCUWrrmaNck"
    assert extract_youtube_video_id("https://youtu.be/XCUWrrmaNck") == "XCUWrrmaNck"
    assert extract_youtube_video_id(
        "https://www.youtube.com/shorts/XCUWrrmaNck"
    ) == "XCUWrrmaNck"
    assert extract_youtube_video_id("https://x.com/foo") is None


def test_extract_links_buckets() -> None:
    text = """
    code: https://github.com/foo/bar
    buy: https://www.amazon.com/dp/B0TEST
    music: https://open.spotify.com/track/123
    other: https://example.com/page
    """
    links = extract_links(text)
    assert any("github.com/foo/bar" in u for u in links["github"])
    assert links["amazon"]
    assert links["music"]
    assert any("example.com" in u for u in links["other"])


def test_classify_unavailable_failures() -> None:
    from ref_cli.enrichment import classify_youtube_fetch_failure

    assert classify_youtube_fetch_failure(
        "api: No YouTube API result; yt-dlp: ERROR: Video unavailable"
    ) == "unavailable"
    assert classify_youtube_fetch_failure(
        "yt-dlp: ERROR: Private video. Sign in if you've been granted access"
    ) == "private"
    assert classify_youtube_fetch_failure("Connection timed out") is None


def test_row_has_usable_transcript(tmp_path: Path) -> None:
    from ref_cli.enrichment import row_has_usable_transcript
    from ref_cli.references_format import parse_data_line

    transcript = tmp_path / "t.json"
    transcript.write_text("{}", encoding="utf-8")

    good = parse_data_line(
        f"2026-07-17T15:49:01|[https://youtu.be/abcdefghijk]|(T)|Ch|YouTube|{transcript}"
    )
    bad = parse_data_line(
        "2026-07-17T15:49:01|[https://youtu.be/abcdefghijk]|(T)|Ch|YouTube|"
        "Transcript unavailable (queued in transcript-pending.md)"
    )
    assert good is not None and row_has_usable_transcript(good)
    assert bad is not None and not row_has_usable_transcript(bad)


def test_unavailable_removes_without_transcript_keeps_with(
    tmp_path: Path,
) -> None:
    from ref_cli.enrichment import handle_unavailable_youtube_rows
    from ref_cli.references_format import apply_row_updates, parse_data_line

    base = tmp_path
    transcript = base / "transcripts" / "deadvid12345.json"
    transcript.parent.mkdir()
    transcript.write_text('{"transcript":[]}', encoding="utf-8")

    refs = base / "references.md"
    refs.write_text(
        "# ref-references version=2\n"
        f"2026-01-01T00:00:00|[https://www.youtube.com/watch?v=deadvid12345]|"
        f"(Has transcript)|Ch|YouTube|{transcript}\n"
        "2026-01-02T00:00:00|[https://www.youtube.com/watch?v=deadvid12345]|"
        "(No transcript)|Ch|YouTube|Transcript unavailable (queued)\n",
        encoding="utf-8",
    )
    from ref_cli.references_format import iter_data_rows

    rows = list(iter_data_rows(str(refs)))
    updates, deletes, summary = handle_unavailable_youtube_rows(
        str(refs),
        "deadvid12345",
        rows,
        references_base=str(base),
        reason="unavailable",
        detail="Video unavailable",
    )
    assert "keep 1" in summary and "remove 1" in summary
    n_upd, n_del = apply_row_updates(
        str(refs), updates, delete_line_numbers=deletes,
    )
    assert n_del == 1
    assert n_upd == 1
    text = refs.read_text(encoding="utf-8")
    assert "No transcript" not in text
    assert "Has transcript" in text
    assert "@meta|unavailable|unavailable" in text
    assert (base / "enrichment" / "youtube" / "videos" / "deadvid12345.json").is_file()


def test_infer_role_music_and_advisor() -> None:
    assert infer_role(category_id="10", category="Music", title="Mix") == "music"
    assert infer_role(
        category_id="28",
        category="Science & Technology",
        title="Claude Code tips",
        links={"github": ["https://github.com/a/b"], "amazon": [], "music": [],
               "patreon": [], "discord": [], "other": []},
    ) == "advisor"
    assert infer_role(
        title="FREE Dark Techno Type Beat Copyright Free",
    ) == "music"


def test_enrich_youtube_reference_stamps_meta(tmp_path: Path, monkeypatch) -> None:
    from ref_cli.enrichment import VideoEnrichment, enrich_youtube_reference
    from ref_cli.references_format import parse_data_line

    base = tmp_path
    refs = base / "references.md"
    refs.write_text(
        "# ref-references version=2\n"
        "2026-07-17T15:49:01|[https://www.youtube.com/watch?v=PqtggjVAi8M]|"
        "(How Are Memories Stored Inside Your Brain)|Kurzgesagt|YouTube|"
        f"{base}/transcripts/PqtggjVAi8M.json\n",
        encoding="utf-8",
    )

    fake = VideoEnrichment(
        video_id="PqtggjVAi8M",
        title="How Are Memories Stored Inside Your Brain",
        channel_id="UCsXVk37bltHxD1rDPwtNM8Q",
        channel_title="Kurzgesagt",
        category_id="27",
        category="Education",
        role="advisor",
        source="test",
    )

    def fake_fetch(video_id, **kwargs):
        assert video_id == "PqtggjVAi8M"
        return fake

    monkeypatch.setattr(
        "ref_cli.enrichment.fetch_youtube_video",
        fake_fetch,
    )

    result = enrich_youtube_reference(
        str(refs),
        "https://www.youtube.com/watch?v=PqtggjVAi8M",
        references_base=str(base),
    )
    assert result is not None
    assert result.role == "advisor"
    assert (base / "enrichment" / "youtube" / "videos" / "PqtggjVAi8M.json").is_file()

    line = refs.read_text(encoding="utf-8").strip().splitlines()[-1]
    row = parse_data_line(line)
    assert row is not None
    assert row.role == "advisor"
    assert row.category == "Education"
    assert row.channel_id == "UCsXVk37bltHxD1rDPwtNM8Q"
    assert "PqtggjVAi8M.json" in row.extra


def test_save_video_and_channel_cards(tmp_path: Path) -> None:
    base = str(tmp_path)
    paths = ensure_enrichment_dirs(base, "youtube")
    assert Path(paths["videos"]).is_dir()
    assert Path(paths["channels"]).is_dir()

    enr = VideoEnrichment(
        video_id="XCUWrrmaNck",
        title="Test",
        channel_id="UCabc123",
        channel_title="Wes Roth",
        category_id="28",
        category="Science & Technology",
        role="advisor",
        links={"github": ["https://github.com/x/y"], "amazon": [], "music": [],
               "patreon": [], "discord": [], "other": []},
        source="test",
    )
    vpath = save_video_card(base, enr)
    assert Path(vpath).is_file()
    data = json.loads(Path(vpath).read_text(encoding="utf-8"))
    assert data["video_id"] == "XCUWrrmaNck"
    assert data["role"] == "advisor"
    assert data["links"]["github"]

    cpath = update_channel_card(base, enr)
    assert cpath and Path(cpath).is_file()
    channel = json.loads(Path(cpath).read_text(encoding="utf-8"))
    assert channel["dominant_role"] == "advisor"
    assert channel["video_count_enriched"] == 1

    # second video bumps counts
    enr2 = VideoEnrichment(
        video_id="abcdefghijk",
        channel_id="UCabc123",
        channel_title="Wes Roth",
        category="Science & Technology",
        role="advisor",
        source="test",
    )
    update_channel_card(base, enr2)
    channel = json.loads(Path(cpath).read_text(encoding="utf-8"))
    assert channel["video_count_enriched"] == 2
    assert video_card_path(base, "XCUWrrmaNck").endswith("XCUWrrmaNck.json")
