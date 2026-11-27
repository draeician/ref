"""Primary-capture correctness and fail-closed lookup semantics."""

from __future__ import annotations

import pytest

from ref_api import service
from ref_cli import cli as ref_cli

HEADER = "# ref-references version=2\n"
REDDIT_URL = "https://www.reddit.com/r/example/comments/123/example"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLabcdefghij"


@pytest.fixture
def env(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(archive))
    monkeypatch.setattr(service.ref_cli, "BASE", str(tmp_path))
    monkeypatch.setattr(
        service.ref_cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts")
    )
    monkeypatch.setattr(
        service.ref_cli,
        "TRANSCRIPT_PENDING_FILE",
        str(tmp_path / "transcripts" / "transcript-pending.md"),
    )
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {"skip_patterns": []})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, cfg: False)
    monkeypatch.setattr(service.ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(service.ref_cli, "get_title_from_url", lambda url: "Example")
    for name in (
        "_queue",
        "_queue_dir",
        "_identity_store",
        "_identity_dir",
        "_idempotency_store",
        "_idempotency_dir",
    ):
        monkeypatch.setattr(service, name, None)
    return tmp_path


def _rows(archive) -> list[str]:
    return [
        line.strip()
        for line in archive.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_discovery_exception_does_not_convert_primary_success(env, monkeypatch):
    archive = env / "references.md"

    def boom(*args, **kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(service, "_enqueue_capture_discovery", boom)

    result = service.process_one(REDDIT_URL)

    assert result.status == "added"
    assert result.primary is not None
    assert result.primary.archive_confirmed is True
    assert result.primary.canonical_url == REDDIT_URL
    assert result.discovery is not None
    assert result.discovery.status == "failed"
    assert result.error is None
    assert len(_rows(archive)) == 1


def test_discovery_source_exception_does_not_convert_primary_success(env, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("import failed")

    monkeypatch.setattr(service, "_discovery_source", boom)

    result = service.process_one(REDDIT_URL)

    assert result.status == "added"
    assert result.primary.archive_confirmed is True
    assert result.discovery.status == "failed"


def test_playlist_child_exception_keeps_playlist_primary(env, monkeypatch):
    archive = env / "references.md"
    monkeypatch.setattr(
        ref_cli,
        "get_youtube_data",
        lambda url: (
            "Playlist",
            "Channel",
            [("vid1", "Child title", "Uploader", "2026-01-01")],
        ),
    )
    monkeypatch.setattr(
        ref_cli, "fetch_youtube_transcript", lambda *a, **k: (None, None)
    )
    monkeypatch.setattr(
        ref_cli, "resolve_transcript_failure_placeholder", lambda *a, **k: "None"
    )
    monkeypatch.setattr(ref_cli, "reference_has_transcript", lambda url: False)

    def boom(*args, **kwargs):
        raise RuntimeError("child write failed")

    monkeypatch.setattr(ref_cli, "update_reference_entry", boom)

    result = service.process_one(PLAYLIST_URL)

    assert result.status == "added"
    assert result.primary is not None
    assert result.primary.archive_confirmed is True
    assert result.primary.canonical_url == PLAYLIST_URL
    assert _rows(archive)[0].endswith(
        f"|[{PLAYLIST_URL}]|(Playlist)|Channel|YouTube"
    )


def test_lookup_deletion_safe_only_for_proven_presence(env):
    archive = env / "references.md"
    stored = "https://example.com/stored"
    original = "https://example.com/original"
    missing = "https://example.com/missing"
    archive.write_text(
        HEADER
        + f"2026-01-01T00:00:00|[{stored}]|(Stored)|General|General\n"
        + "2026-01-01T00:00:00|[https://example.com/path/child]|(Child)|General|General\n",
        encoding="utf-8",
    )
    service._get_identity_store().record(original, stored)
    service._get_identity_store().record(missing, "https://example.com/absent")

    exact = service.lookup_url(stored)
    assert exact.status == "exists"
    assert exact.deletion_safe is True

    canonical = service.lookup_url(original)
    assert canonical.status == "canonical"
    assert canonical.deletion_safe is True

    absent = service.lookup_url("https://example.com/path")
    assert absent.status == "absent"
    assert absent.deletion_safe is False
    assert "not proof" in absent.message

    unresolved = service.lookup_url(missing)
    assert unresolved.status == "unknown"
    assert unresolved.deletion_safe is False

    invalid = service.lookup_url("not-a-url")
    assert invalid.status == "unknown"
    assert invalid.deletion_safe is False
