"""Tests for gzip / plain backups."""

from __future__ import annotations

import gzip
from pathlib import Path

from ref_cli.backup_util import backup_file
from ref_cli.cli import create_backup
from ref_cli.references_format import migrate_references_file


def test_backup_file_gzip_default(tmp_path: Path) -> None:
    src = tmp_path / "references.md"
    content = b"hello backup\n" * 100
    src.write_bytes(content)
    dest = backup_file(str(src), compress=True, style="timestamp_prefix")
    assert dest.endswith(".gz")
    assert Path(dest).is_file()
    with gzip.open(dest, "rb") as handle:
        assert handle.read() == content


def test_backup_file_nocompress(tmp_path: Path) -> None:
    src = tmp_path / "references.md"
    src.write_text("plain\n", encoding="utf-8")
    dest = backup_file(str(src), compress=False, style="timestamp_prefix")
    assert not dest.endswith(".gz")
    assert Path(dest).read_text(encoding="utf-8") == "plain\n"


def test_backup_file_suffix_style_gzip(tmp_path: Path) -> None:
    src = tmp_path / "references.md"
    src.write_text("x\n", encoding="utf-8")
    dest = backup_file(str(src), compress=True, style="suffix")
    assert ".bak-" in dest
    assert dest.endswith(".gz")
    with gzip.open(dest, "rt", encoding="utf-8") as handle:
        assert handle.read() == "x\n"


def test_create_backup_gzip(tmp_path: Path) -> None:
    src = tmp_path / "references.md"
    src.write_text("data\n", encoding="utf-8")
    path = create_backup(str(src), compress=True)
    assert path is not None
    assert path.endswith(".gz")


def test_migrate_backup_is_gzip(tmp_path: Path) -> None:
    path = tmp_path / "references.md"
    path.write_text(
        "Date|URL|Title|Source|TypG\n"
        "2026-07-08T01:12:39|[https://youtu.be/XCUWrrmaNck]|(T)|Ch|YouTube\n",
        encoding="utf-8",
    )
    changed, msg = migrate_references_file(str(path), backup=True, compress=True)
    assert changed
    assert ".gz" in msg
    gz_backups = list(tmp_path.glob("references.md.bak-*.gz"))
    assert gz_backups
