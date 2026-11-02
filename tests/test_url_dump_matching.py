"""Tests for domain matching and the read-only URL dump listing."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

import pytest

from ref_api.listing import list_urls_by_domain
from ref_cli.domain_match import hostname_matches, normalize_domain, url_hostname


def _row(ts: str, url: str, title: str = "Title") -> str:
    return f"{ts}|[{url}]|({title})|General|General"


# ---------------------------------------------------------------------------
# normalize_domain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("Example.COM", "example.com"),
        ("  example.com  ", "example.com"),
        ("example.com.", "example.com"),
        ("docs.Example.com", "docs.example.com"),
        ("sub-domain_2.example.com", "sub-domain_2.example.com"),
        ("xn--nic-1oa.com", "xn--nic-1oa.com"),
    ],
)
def test_normalize_domain_accepts_bare_domains(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "com",  # single label / TLD-only dump
        ".example.com",
        "example..com",
        "-bad.com",
        "bad-.com",
        "user@example.com",
        "https://example.com/path",
        "//example.com/path",
        "/example.com",
        "example.com:8080",
        "exa mple.com",
        "example.com path",
        "?" + "a" * 300,
    ],
)
def test_normalize_domain_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(raw)


def test_normalize_domain_error_names_the_value() -> None:
    with pytest.raises(ValueError, match="Invalid domain 'example.com:8080'"):
        normalize_domain("example.com:8080")


# ---------------------------------------------------------------------------
# hostname matching (parsed host, never substring)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com",
        "http://www.example.com/x?y=1#z",
        "https://a.b.c.example.com/deep/path",
        "http://EXAMPLE.COM/Path-With-Case",
        "https://user:pw@sub.example.com:8443/p?q=1",
        "https://example.com./trailing-dot/",
        "https://example.com/search?q=hello world&x=1#frag-üñîçødé",
    ],
)
def test_hostname_matches_domain_and_subdomains(url: str) -> None:
    assert hostname_matches(url, "example.com") is True


@pytest.mark.parametrize(
    "url",
    [
        "https://notexample.com/",
        "https://myexample.com/a/b",
        "https://example.co/",
        "https://example.com.evil.net/x",
        "https://evil.example.org/example.com",
        "https://evil.com/?redirect=https://example.com/path",
        "http://127.0.0.1:8000/urls?domain=example.com",
        "not a url at all",
        "",
    ],
)
def test_hostname_matches_rejects_false_positives(url: str) -> None:
    assert hostname_matches(url, "example.com") is False


def test_url_hostname_is_lowercased_and_scheme_tolerant() -> None:
    assert url_hostname("HTTPS://WWW.Example.COM/a?b=1#c") == "www.example.com"
    assert url_hostname("https://Example.COM./x") == "example.com"
    # Scheme-less stored values still resolve by authority, not substring.
    assert url_hostname("example.com/path?q=1") == "example.com"
    assert url_hostname("") is None


def test_subdomain_match_is_label_anchored() -> None:
    assert hostname_matches("https://sub.example.com/", "example.com") is True
    assert hostname_matches("https://sub.example.org/", "example.com") is False
    # A parent domain does not match a deeper dump request.
    assert hostname_matches("https://example.com/", "sub.example.com") is False


# ---------------------------------------------------------------------------
# list_urls_by_domain (server-side listing helper)
# ---------------------------------------------------------------------------

BASE_TS = "2026-01-01T00:00:00"


def datetime_ts(hours: int) -> str:
    """Deterministic timestamp offset from a fixed base (no clock dependence)."""
    from datetime import datetime

    return (datetime.fromisoformat(BASE_TS) + timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


@pytest.fixture
def refs_file(tmp_path: Path) -> Path:
    path = tmp_path / "references.md"
    lines = [
        "# ref-references version=2",
        "# format: timestamp|[url]|(title)|uploader|source[|extra…]",
        # Timestamps are deliberately out of file order so the newest-first
        # guarantee cannot be satisfied by simply reversing the file.
        _row(datetime_ts(6), "https://docs.example.com/guide/a_b#c"),
        _row(datetime_ts(1), "https://example.com/oldest?keep=1"),
        _row(datetime_ts(2), "https://notexample.com/decoy"),
        _row(datetime_ts(5), "https://www.example.com/search?q=hello world&x=1#frag-üñîçødé"),
        _row(datetime_ts(4), "https://WWW.Example.COM/Mixed-Case?q=1&x=2#frag"),
        _row(datetime_ts(3), "https://example.com.evil.net/decoy"),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_list_urls_by_domain_exact_and_subdomain_newest_first(refs_file: Path) -> None:
    urls = list_urls_by_domain(domain="example.com", file_path=str(refs_file))

    assert urls == [
        "https://docs.example.com/guide/a_b#c",
        "https://www.example.com/search?q=hello world&x=1#frag-üñîçødé",
        "https://WWW.Example.COM/Mixed-Case?q=1&x=2#frag",
        "https://example.com/oldest?keep=1",
    ]


def test_list_urls_by_domain_is_case_insensitive_on_the_argument(
    refs_file: Path,
) -> None:
    assert list_urls_by_domain(
        domain="EXAMPLE.com", file_path=str(refs_file)
    ) == list_urls_by_domain(domain="example.com", file_path=str(refs_file))


def test_list_urls_by_domain_preserves_exact_url_strings(refs_file: Path) -> None:
    urls = list_urls_by_domain(domain="example.com", file_path=str(refs_file))

    # Case, query separators, spaces, and unicode fragments survive untouched.
    assert "https://WWW.Example.COM/Mixed-Case?q=1&x=2#frag" in urls
    assert "https://www.example.com/search?q=hello world&x=1#frag-üñîçødé" in urls


def test_list_urls_by_domain_empty_result(tmp_path: Path) -> None:
    path = tmp_path / "references.md"
    path.write_text(_row(datetime_ts(1), "https://other.example/only") + "\n", "utf-8")

    assert list_urls_by_domain(domain="example.com", file_path=str(path)) == []


def test_list_urls_by_domain_missing_archive(tmp_path: Path) -> None:
    assert (
        list_urls_by_domain(
            domain="example.com", file_path=str(tmp_path / "absent.md")
        )
        == []
    )


def test_list_urls_by_domain_rejects_malformed_domain_before_reading(
    refs_file: Path,
) -> None:
    with pytest.raises(ValueError, match="Invalid domain"):
        list_urls_by_domain(domain="https://example.com/x", file_path=str(refs_file))


def test_list_urls_by_domain_is_read_only(refs_file: Path, tmp_path: Path) -> None:
    before = hashlib.sha256(refs_file.read_bytes()).hexdigest()
    files_before = sorted(p.name for p in tmp_path.iterdir())

    list_urls_by_domain(domain="example.com", file_path=str(refs_file))

    assert hashlib.sha256(refs_file.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == files_before
