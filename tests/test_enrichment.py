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
