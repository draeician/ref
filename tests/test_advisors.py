"""Tests for trusted-advisor scanning over references.md lines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ref_cli.advisors import (
    extract_by_author,
    extract_x_display_name,
    extract_x_handle,
    format_table,
    main,
    parse_line,
    platform_of,
    render_csv,
    render_json,
    render_markdown,
    resolve_web_advisor,
    scan_advisors,
)


SAMPLE_LINES = """\
2026-07-08T01:11:41|[https://www.youtube.com/watch?v=-LYy_voO4vA]|(Never Say These 10 Things To Your Boss)|A Life After Layoff|YouTube|Transcript unavailable
2026-07-08T01:12:39|[https://www.youtube.com/watch?v=XCUWrrmaNck]|(Claude Code is about to break everything)|Wes Roth|YouTube|Transcript unavailable
2026-07-08T01:42:40|[https://www.youtube.com/watch?v=KX0GurmgAoo]|(90 of AI Users Are Getting Mediocre Output)|AI News & Strategy Daily | Nate B Jones|YouTube|Transcript unavailable
2026-07-08T01:47:32|[https://www.youtube.com/watch?v=q6p-_W6_VoM]|(Going Slower Feels Safer)|AI News & Strategy Daily | Nate B Jones|YouTube|Transcript unavailable
2026-07-08T01:12:57|[https://x.com/tom_doerr/status/2009624580369903652]|(Tom Dörr on X: "Headless browser for AI agents")|General|General
2026-07-08T01:16:06|[https://x.com/tom_doerr/status/2011023446835151097]|(Tom Dörr on X: "Trains models from unlabeled images")|General|General
2026-07-08T01:17:26|[https://x.com/PythonHub/status/2011955437201993964]|(Python Hub on X: "Jsonic – Python JSON serialization")|General|General
2026-07-08T01:12:55|[https://github.com/solidtime-io/solidtime]|(GitHub - solidtime-io/solidtime)|General|General
2026-07-09T10:00:00|[https://www.youtube.com/watch?v=abc12345678]|(Second Wes Roth video)|Wes Roth|YouTube|some/transcript.md
2026-07-08T12:00:00|[https://xhinker.medium.com/some-post-aaaa]|(A post about tools)|General|General
2026-07-08T12:01:00|[https://xhinker.medium.com/another-post-bbbb]|(Another post)|General|General
2026-07-08T12:02:00|[https://medium.com/@Owenwarner/germany-just-did-something-5f58d65b46a8]|(Germany Just Did Something | by Owen Warner | Medium)|General|General
2026-07-08T12:03:00|[https://medium.com/@Owenwarner/another-story-zzzz]|(Another Story | by Owen Warner | Medium)|General|General
2026-07-08T12:04:00|[https://medium.com/data-science-collective/dark-side-of-ai-aaaa]|(The Dark Side of AI | by Hayanan | Data Science Collective)|General|General
2026-07-08T12:05:00|[https://virtualizationhowto.com/post-one]|(Proxmox tip one)|General|General
2026-07-08T12:06:00|[https://virtualizationhowto.com/post-two]|(Proxmox tip two)|General|General
2026-07-08T12:07:00|[https://www.reddit.com/r/LocalLLaMA/comments/abc/hi]|(reddit noise)|General|General
2026-07-08T12:08:00|[https://arxiv.org/abs/2502.14802]|(paper noise)|General|General
"""


@pytest.fixture
def refs_file(tmp_path: Path) -> Path:
    path = tmp_path / "references.md"
    path.write_text(SAMPLE_LINES, encoding="utf-8")
    return path


def test_parse_line_basic_youtube() -> None:
    line = (
        "2026-07-08T01:12:39|[https://www.youtube.com/watch?v=XCUWrrmaNck]|"
        "(Claude Code is about to break everything)|Wes Roth|YouTube|Transcript unavailable"
    )
    entry = parse_line(line, line_number=1)
    assert entry is not None
    assert entry.timestamp == "2026-07-08T01:12:39"
    assert entry.url == "https://www.youtube.com/watch?v=XCUWrrmaNck"
    assert entry.title == "Claude Code is about to break everything"
    assert entry.uploader == "Wes Roth"
    assert entry.source == "YouTube"


def test_parse_line_uploader_with_pipe() -> None:
    line = (
        "2026-07-08T01:42:40|[https://www.youtube.com/watch?v=KX0GurmgAoo]|"
        "(90 of AI Users Are Getting Mediocre Output)|"
        "AI News & Strategy Daily | Nate B Jones|YouTube|Transcript unavailable"
    )
    entry = parse_line(line)
    assert entry is not None
    assert entry.uploader == "AI News & Strategy Daily | Nate B Jones"
    assert entry.source == "YouTube"


def test_platform_and_handle_extraction() -> None:
    assert platform_of("https://www.youtube.com/watch?v=abc") == "youtube"
    assert platform_of("https://youtu.be/abc") == "youtube"
    assert platform_of("https://x.com/tom_doerr/status/1") == "x"
    assert platform_of("https://twitter.com/PythonHub/status/1") == "x"
    assert platform_of("https://virtualizationhowto.com/post") == "web"
    assert platform_of("https://medium.com/@someone/post") == "web"
    # Aggregators / non-author platforms are not advisors
    assert platform_of("https://github.com/foo/bar") is None
    assert platform_of("https://www.reddit.com/r/foo") is None
    assert platform_of("https://arxiv.org/abs/123") is None

    assert extract_x_handle("https://x.com/tom_doerr/status/123") == "tom_doerr"
    assert extract_x_handle("https://x.com/i/status/123") is None
    assert extract_x_display_name('Tom Dörr on X: "hello"') == "Tom Dörr"
    assert extract_by_author("Dark Side | by Hayanan | Data Science") == "Hayanan"


def test_resolve_web_advisor_variants() -> None:
    sub = parse_line(
        "2026-07-08T12:00:00|[https://xhinker.medium.com/some-post]|(A post)|General|General"
    )
    assert sub is not None
    ident = resolve_web_advisor(sub)
    assert ident is not None
    assert ident.key == "medium:xhinker"
    assert ident.profile_url == "https://xhinker.medium.com"

    at = parse_line(
        "2026-07-08T12:00:00|[https://medium.com/@Owenwarner/story]|"
        "(Germany | by Owen Warner | Medium)|General|General"
    )
    assert at is not None
    ident = resolve_web_advisor(at)
    assert ident is not None
    assert ident.key == "medium:owenwarner"
    assert ident.handle == "@Owenwarner"

    site = parse_line(
        "2026-07-08T12:00:00|[https://virtualizationhowto.com/a]|(Tip)|General|General"
    )
    assert site is not None
    ident = resolve_web_advisor(site)
    assert ident is not None
    assert ident.key == "site:virtualizationhowto.com"


def test_scan_ranks_and_filters(refs_file: Path) -> None:
    all_advisors = scan_advisors(str(refs_file), min_count=1)
    keys = {(a.platform, a.key) for a in all_advisors}
    assert ("youtube", "wes roth") in keys
    assert ("youtube", "ai news & strategy daily | nate b jones") in keys
    assert ("x", "tom_doerr") in keys
    assert ("x", "pythonhub") in keys
    assert ("web", "medium:xhinker") in keys
    assert ("web", "medium:owenwarner") in keys
    assert ("web", "medium:hayanan") in keys  # from | by Author |
    assert ("web", "site:virtualizationhowto.com") in keys
    # Aggregators must not appear
    assert not any("github" in a.key for a in all_advisors)
    assert not any("reddit" in a.key for a in all_advisors)
    assert not any("arxiv" in a.key for a in all_advisors)

    # Frequency filter
    frequent = scan_advisors(str(refs_file), min_count=2)
    frequent_keys = {(a.platform, a.key) for a in frequent}
    assert ("x", "tom_doerr") in frequent_keys
    assert ("youtube", "wes roth") in frequent_keys
    assert ("web", "medium:xhinker") in frequent_keys
    assert ("web", "site:virtualizationhowto.com") in frequent_keys
    assert ("x", "pythonhub") not in frequent_keys  # only 1 save
    assert ("web", "medium:hayanan") not in frequent_keys  # only 1 save

    # Platform filter
    yt_only = scan_advisors(str(refs_file), platforms=("youtube",), min_count=1)
    assert all(a.platform == "youtube" for a in yt_only)

    web_only = scan_advisors(str(refs_file), platforms=("web",), min_count=2)
    assert all(a.platform == "web" for a in web_only)
    assert len(web_only) >= 2

    # Ranking: highest count first
    assert frequent[0].count >= frequent[-1].count


def test_x_advisor_fields(refs_file: Path) -> None:
    advisors = scan_advisors(str(refs_file), platforms=("x",), min_count=2)
    tom = next(a for a in advisors if a.key == "tom_doerr")
    assert tom.handle == "@tom_doerr"
    assert tom.profile_url == "https://x.com/tom_doerr"
    assert tom.display_name == "Tom Dörr"
    assert tom.count == 2


def test_render_formats(refs_file: Path) -> None:
    advisors = scan_advisors(str(refs_file), min_count=2)
    md = render_markdown(advisors, path=str(refs_file))
    assert "Trusted Advisors" in md
    assert "YouTube" in md
    assert "@tom_doerr" in md
    assert "Web / blog" in md
    assert "virtualizationhowto.com" in md or "xhinker" in md
    # Columns should be space-aligned, not markdown pipes
    assert "| Rank |" not in md
    assert "Rank" in md and "Channel" in md

    payload = json.loads(render_json(advisors, path=str(refs_file)))
    assert payload["total"] == len(advisors)
    assert payload["advisors"][0]["count"] >= 1
    assert "target" in payload["advisors"][0]

    csv_text = render_csv(advisors)
    assert "platform" in csv_text
    assert "tom_doerr" in csv_text


def test_format_table_columns_align() -> None:
    lines = format_table(
        ['Rank', 'Channel', 'Saves'],
        [
            ['1', 'Short', '9'],
            ['12', 'A Much Longer Channel Name', '869'],
        ],
        aligns=['right', 'left', 'right'],
    )
    assert len(lines) == 4  # header, sep, 2 rows
    # Every data row (and header) should share the same display length
    widths = {len(line) for line in lines}
    assert len(widths) == 1
    # Rank column right-aligned: single digit has a leading space vs double
    assert lines[2].startswith(' ')
    assert '869' in lines[3]
    assert 'A Much Longer Channel Name' in lines[3]


def test_keyboard_interrupt_exits_cleanly(monkeypatch, capsys) -> None:
    def boom(_argv=None):
        raise KeyboardInterrupt

    monkeypatch.setattr('ref_cli.advisors._main', boom)
    code = main([])
    assert code == 130
    err = capsys.readouterr().err
    assert 'Interrupted' in err
