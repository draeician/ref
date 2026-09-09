"""Tests for ref-api listing helpers (last-N and duration window)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ref_api.listing import list_urls, parse_list_duration


def _row(ts: str, url: str, title: str = "Title") -> str:
    return f"{ts}|[{url}]|({title})|General|General"


@pytest.fixture
def refs_file(tmp_path: Path) -> Path:
    path = tmp_path / "references.md"
    now = datetime.now().replace(microsecond=0)
    lines = [
        "# references",
        _row((now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"), "https://example.com/old"),
        _row((now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S"), "https://example.com/mid"),
        _row((now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S"), "https://example.com/new"),
        _row(now.strftime("%Y-%m-%dT%H:%M:%S"), "https://example.com/newest"),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_parse_list_duration_forms() -> None:
    assert parse_list_duration("5 min") == timedelta(minutes=5)
    assert parse_list_duration("5 mins") == timedelta(minutes=5)
    assert parse_list_duration("5m") == timedelta(minutes=5)
    assert parse_list_duration("1 hour") == timedelta(hours=1)
    assert parse_list_duration("1h") == timedelta(hours=1)
    assert parse_list_duration("2 days") == timedelta(days=2)
    assert parse_list_duration("2d") == timedelta(days=2)


def test_parse_list_duration_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid list duration"):
        parse_list_duration("fortnight")
    with pytest.raises(ValueError, match="Invalid list duration"):
        parse_list_duration("1")


def test_list_urls_last_n(refs_file: Path) -> None:
    urls = list_urls(limit=2, file_path=str(refs_file))
    assert urls == [
        "https://example.com/newest",
        "https://example.com/new",
    ]


def test_list_urls_since_one_hour(refs_file: Path) -> None:
    urls = list_urls(since=timedelta(hours=1), file_path=str(refs_file))
    assert urls == [
        "https://example.com/newest",
        "https://example.com/new",
        "https://example.com/mid",
    ]


def test_list_urls_since_five_min(refs_file: Path) -> None:
    urls = list_urls(since=timedelta(minutes=5), file_path=str(refs_file))
    assert urls == [
        "https://example.com/newest",
        "https://example.com/new",
    ]


def test_list_urls_digit_vs_duration_window(refs_file: Path) -> None:
    assert len(list_urls(limit=100, file_path=str(refs_file))) == 4
    assert "https://example.com/old" not in list_urls(
        since=timedelta(hours=1), file_path=str(refs_file)
    )
