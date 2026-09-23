"""Tests for ref-reddit-extract CLI and its --apply / --no-write-refs semantics."""

from __future__ import annotations

from pathlib import Path

from ref_cli import reddit_extract


def _write_refs(tmp_path: Path) -> Path:
    refs = tmp_path / "references.md"
    refs.write_text(
        "# ref-references version=2\n"
        "2026-01-01T00:00:00|[https://www.reddit.com/r/test/comments/abc123/slug/]"
        "|(a post)|General|General\n",
        encoding="utf-8",
    )
    return refs


def _patch_discovery(monkeypatch, links):
    monkeypatch.setattr(
        reddit_extract, "discover_outbound_urls", lambda url: list(links)
    )


def _patch_process_url(monkeypatch):
    calls = []

    def fake_process_url(url, force=False):
        calls.append(url)

    monkeypatch.setattr("ref_cli.cli.process_url", fake_process_url)
    return calls


def test_apply_ingests_discovered_links(tmp_path, monkeypatch):
    refs = _write_refs(tmp_path)
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(["--file", str(refs), "--apply"])

    assert code == 0
    assert calls == ["https://example.com/out"]


def test_no_write_refs_suppresses_reference_writes(tmp_path, monkeypatch):
    refs = _write_refs(tmp_path)
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(["--file", str(refs), "--no-write-refs"])

    assert code == 0
    assert calls == []
    assert "example.com/out" not in refs.read_text()


def test_apply_with_no_write_refs_still_processes(tmp_path, monkeypatch):
    refs = _write_refs(tmp_path)
    out = tmp_path / "links.txt"
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(
        ["--file", str(refs), "--out", str(out), "--apply", "--no-write-refs"]
    )

    assert code == 0
    # The normal ingestion path IS invoked (not skipped) under --no-write-refs.
    assert calls == ["https://example.com/out"]
    # Other mutation still happened: outbound links written to --out.
    assert out.read_text().strip() == "https://example.com/out"


def test_apply_no_write_refs_processes_but_does_not_mutate_refs(tmp_path, monkeypatch):
    """Real process_url runs under --apply --no-write-refs, but references.md is
    left byte-for-byte unchanged while non-reference processing still occurs."""
    from ref_cli import cli

    refs = _write_refs(tmp_path)
    original = refs.read_bytes()

    monkeypatch.setattr(cli, "UNIFIED", str(refs))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)

    fetched = []

    def fake_get_title(url):
        fetched.append(url)
        return "Discovered Title"

    monkeypatch.setattr(cli, "get_title_from_url", fake_get_title)
    _patch_discovery(monkeypatch, ["https://example.com/out"])

    code = reddit_extract.main(["--file", str(refs), "--apply", "--no-write-refs"])

    assert code == 0
    # Non-reference processing happened: the title was fetched for the link.
    assert fetched == ["https://example.com/out"]
    # references.md untouched (byte-for-byte).
    assert refs.read_bytes() == original


def test_apply_writes_refs_via_normal_path(tmp_path, monkeypatch):
    """Plain --apply uses the normal capture path and writes references.md."""
    from ref_cli import cli

    refs = _write_refs(tmp_path)

    monkeypatch.setattr(cli, "UNIFIED", str(refs))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)
    monkeypatch.setattr(cli, "get_title_from_url", lambda url: "Discovered Title")
    _patch_discovery(monkeypatch, ["https://example.com/out"])

    code = reddit_extract.main(["--file", str(refs), "--apply"])

    assert code == 0
    assert "https://example.com/out" in refs.read_text()


def test_outbound_links_feed_normal_pipeline_not_silo(tmp_path, monkeypatch):
    # The discovered links are handed to cli.process_url (the normal capture
    # path) — no Reddit-specific persistence is written anywhere.
    refs = _write_refs(tmp_path)
    _patch_discovery(monkeypatch, ["https://example.com/out", "https://github.com/x/y"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(["--file", str(refs), "--apply"])

    assert code == 0
    assert calls == ["https://example.com/out", "https://github.com/x/y"]


def test_dry_run_default_writes_nothing(tmp_path, monkeypatch):
    refs = _write_refs(tmp_path)
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(["--file", str(refs)])

    assert code == 0
    assert calls == []
    assert "example.com/out" not in refs.read_text()


def test_explicit_targets_do_not_require_file(tmp_path, monkeypatch):
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(
        ["--apply", "https://www.reddit.com/r/test/comments/abc123/slug/"]
    )

    assert code == 0
    assert calls == ["https://example.com/out"]


def test_non_reddit_target_is_skipped(tmp_path, monkeypatch):
    _patch_discovery(monkeypatch, ["https://example.com/out"])
    calls = _patch_process_url(monkeypatch)

    code = reddit_extract.main(["--apply", "https://example.com/not-reddit"])

    assert code == 0
    assert calls == []
