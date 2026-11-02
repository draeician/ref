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
# regression: embedded "//" and non-web URIs (scheme-less stored values)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        # A scheme in a query must not swallow the authority.
        ("example.com/path?q=https://other.com", "example.com"),
        # Empty path segments are part of the path, not an authority marker.
        ("example.com/foo//bar", "example.com"),
        ("sub.example.com/foo//bar?q=1#https://cdn.example.net/x", "sub.example.com"),
        # Scheme-relative values keep their own authority.
        ("//example.com/x?u=https://cdn.example.net/y", "example.com"),
    ],
)
def test_url_hostname_ignores_embedded_double_slashes(url: str, expected_host: str) -> None:
    assert url_hostname(url) == expected_host


@pytest.mark.parametrize(
    ("url", "domain", "expected"),
    [
        ("example.com/path?q=https://other.com", "example.com", True),
        ("example.com/foo//bar", "example.com", True),
        ("mailto:user@example.com", "example.com", False),
        ("user@example.com", "example.com", False),
    ],
)
def test_hostname_matches_embedded_slashes_and_non_web_uris(
    url: str, domain: str, expected: bool
) -> None:
    assert hostname_matches(url, domain) is expected


@pytest.mark.parametrize(
    "url",
    [
        "mailto:someone@sub.example.com",
        "user@example.com/reset",
        "MAILTO:Someone@Example.COM",
        "tel:+15551234567",
        'data:text/html,<a href="http://example.com">',
        "urn:example.com:x",
        "magnet:?xt=urn:btih:0123abcd",
    ],
)
def test_hostname_matches_rejects_nonhierarchical_uris(url: str) -> None:
    assert hostname_matches(url, "example.com") is False


def test_hostname_matches_ignores_a_query_embedded_foreign_host() -> None:
    # The stored value belongs to example.com; the URL inside its query does not.
    url = "example.com/path?q=https://other.com"
    assert hostname_matches(url, "example.com") is True
    assert hostname_matches(url, "other.com") is False


@pytest.mark.parametrize(
    ("url", "expected_host"),
    [
        # Credentials are honoured when the value carries its own hierarchical scheme.
        ("https://user:pw@example.com/inbox", "example.com"),
        ("http://admin:t3st@sub.example.com:8443/p?q=1", "sub.example.com"),
        # Scheme-less host:port is still a legitimate stored authority.
        ("example.com:8443/path", "example.com"),
        ("example.com:8443/foo//bar?q=a//b", "example.com"),
    ],
)
def test_url_hostname_still_parses_legitimate_authorities(url: str, expected_host: str) -> None:
    assert url_hostname(url) == expected_host


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


@pytest.fixture
def scheme_less_refs_file(tmp_path: Path) -> Path:
    """Archive of scheme-less stored values, including embedded ``//`` and emails."""
    path = tmp_path / "references.md"
    lines = [
        "# ref-references version=2",
        _row(datetime_ts(4), "example.com/path?q=https://other.com"),
        _row(datetime_ts(3), "example.com/foo//bar"),
        _row(datetime_ts(2), "mailto:user@example.com"),
        _row(datetime_ts(1), "user@example.com"),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_list_urls_by_domain_matches_scheme_less_embedded_slashes(
    scheme_less_refs_file: Path,
) -> None:
    urls = list_urls_by_domain(domain="example.com", file_path=str(scheme_less_refs_file))

    # Both stored values match by authority and are returned exactly as stored;
    # the mailto:/email rows are not web URLs and stay out of the dump.
    assert urls == ["example.com/path?q=https://other.com", "example.com/foo//bar"]


def test_list_urls_by_domain_does_not_dump_a_query_embedded_host(
    scheme_less_refs_file: Path,
) -> None:
    assert list_urls_by_domain(domain="other.com", file_path=str(scheme_less_refs_file)) == []
