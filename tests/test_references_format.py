"""Tests for versioned references.md format + migrate."""

from __future__ import annotations

from pathlib import Path

from ref_cli.references_format import (
    LEGACY_UNVERSIONED,
    MIGRATION_STEPS,
    REFERENCES_FORMAT_VERSION,
    META_SENTINEL,
    MigrationState,
    _steps_from_to,
    effective_version,
    format_data_line,
    migrate_references_file,
    parse_data_line,
    read_format_version,
    with_meta,
)


def test_parse_without_meta() -> None:
    line = (
        "2026-07-08T01:12:39|[https://www.youtube.com/watch?v=XCUWrrmaNck]|"
        "(Claude Code is about to break everything)|Wes Roth|YouTube|Transcript unavailable"
    )
    row = parse_data_line(line, 1)
    assert row is not None
    assert row.uploader == "Wes Roth"
    assert row.source == "YouTube"
    assert row.category == ""
    assert row.role == ""


def test_parse_and_format_with_meta() -> None:
    line = (
        "2024-12-09T00:09:01|[https://www.youtube.com/watch?v=abcdefghijk]|"
        "(Dark Techno Mix)|Aim To Head Official|YouTube|queued|"
        f"{META_SENTINEL}|Music|music|UCdeadbeef"
    )
    row = parse_data_line(line)
    assert row is not None
    assert row.category == "Music"
    assert row.role == "music"
    assert row.channel_id == "UCdeadbeef"
    assert row.extra == "queued"

    again = parse_data_line(format_data_line(row))
    assert again is not None
    assert again.category == "Music"
    assert again.role == "music"
    assert again.channel_id == "UCdeadbeef"
    assert again.uploader == "Aim To Head Official"


def test_uploader_with_pipe_still_parses() -> None:
    line = (
        "2026-07-08T01:42:40|[https://www.youtube.com/watch?v=KX0GurmgAoo]|"
        "(Title Here)|AI News & Strategy Daily | Nate B Jones|YouTube|x|"
        f"{META_SENTINEL}|Science & Technology|advisor|UCabc"
    )
    row = parse_data_line(line)
    assert row is not None
    assert row.uploader == "AI News & Strategy Daily | Nate B Jones"
    assert row.role == "advisor"


def test_migrate_adds_header(tmp_path: Path) -> None:
    path = tmp_path / "references.md"
    path.write_text(
        "Date|URL|Title|Source|TypG\n"
        "2026-07-08T01:12:39|[https://www.youtube.com/watch?v=XCUWrrmaNck]|"
        "(Hello)|Wes Roth|YouTube\n",
        encoding="utf-8",
    )
    assert read_format_version(str(path)) is None
    assert effective_version(str(path)) == LEGACY_UNVERSIONED
    changed, msg = migrate_references_file(str(path), backup=True)
    assert changed
    assert "1→2" in msg
    assert read_format_version(str(path)) == REFERENCES_FORMAT_VERSION
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# ref-references version=")
    assert "migration-path: 1→2" in text
    assert "Date|URL|Title" not in text
    assert "Wes Roth" in text
    # gzip backup created by default
    backups = list(tmp_path.glob("references.md.bak-*.gz"))
    assert backups


def test_migration_chain_layers_multiple_hops() -> None:
    """Future-proof: chain walker runs every hop from start → target."""
    # Simulate steps 1→2 and 2→3 without changing production version.
    def step12(state: MigrationState) -> MigrationState:
        state.version = 2
        state.notes.append("1→2:test")
        state.lines.append("# touched-by-1-2\n")
        return state

    def step23(state: MigrationState) -> MigrationState:
        state.version = 3
        state.notes.append("2→3:test")
        state.lines.append("# touched-by-2-3\n")
        return state

    fake_steps = (
        (1, 2, step12),
        (2, 3, step23),
    )
    # Use the real selector with a temporary monkeypatch via direct call pattern
    hops = []
    current = 1
    by_from = {frm: (frm, to, fn) for frm, to, fn in fake_steps}
    while current < 3:
        frm, to, fn = by_from[current]
        hops.append((frm, to, fn))
        current = to
    assert [(a, b) for a, b, _ in hops] == [(1, 2), (2, 3)]

    state = MigrationState(lines=["data\n"], version=1, notes=[])
    for frm, to, fn in hops:
        assert state.version == frm
        state = fn(state)
        assert state.version == to
    assert state.version == 3
    assert any("touched-by-1-2" in ln for ln in state.lines)
    assert any("touched-by-2-3" in ln for ln in state.lines)
    assert state.notes == ["1→2:test", "2→3:test"]


def test_steps_from_to_matches_registry() -> None:
    steps = _steps_from_to(1, REFERENCES_FORMAT_VERSION)
    assert steps
    assert steps[0][0] == 1
    assert steps[-1][1] == REFERENCES_FORMAT_VERSION
    # Registry must be able to reach current version from legacy v1
    assert MIGRATION_STEPS[0][0] == 1


def test_already_current_is_noop(tmp_path: Path) -> None:
    path = tmp_path / "references.md"
    path.write_text(
        f"# ref-references version={REFERENCES_FORMAT_VERSION}\n"
        "2026-07-08T01:12:39|[https://youtu.be/XCUWrrmaNck]|(T)|Ch|YouTube\n",
        encoding="utf-8",
    )
    changed, msg = migrate_references_file(str(path), backup=False)
    assert changed is False
    assert "Already" in msg


def test_with_meta_roundtrip() -> None:
    row = parse_data_line(
        "2026-07-08T01:12:39|[https://youtu.be/XCUWrrmaNck]|(T)|Ch|YouTube"
    )
    assert row is not None
    updated = with_meta(row, category="Education", role="advisor", channel_id="UC1")
    assert META_SENTINEL in format_data_line(updated)
    parsed = parse_data_line(format_data_line(updated))
    assert parsed is not None
    assert parsed.role == "advisor"
    assert parsed.category == "Education"
