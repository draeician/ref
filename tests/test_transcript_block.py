"""Deterministic tests for the persisted YouTube transcript IP-block cooldown."""

import json
import logging
import sys
import threading
import time
import types
from pathlib import Path

import pytest
from youtube_transcript_api._errors import RequestBlocked, TranscriptsDisabled

from ref_cli import cli, transcript_block

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"
VIDEO_URL_A = f"https://www.youtube.com/watch?v={VIDEO_A}"
T0 = 1_700_000_000.0


def _force_legacy_pending(monkeypatch):
    """Make local_transcribe import fail and lt unavailable (pending-file path)."""
    monkeypatch.setitem(sys.modules, "local_transcribe", None)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", None)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)


def _install_fake_queue_api(monkeypatch, enqueue_fn):
    queue_api = types.ModuleType("local_transcribe.queue_api")
    queue_api.enqueue_youtube_safe = enqueue_fn
    lt = types.ModuleType("local_transcribe")
    lt.queue_api = queue_api
    monkeypatch.setitem(sys.modules, "local_transcribe", lt)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", queue_api)


def _block_provider(monkeypatch):
    """Any provider (enhanced or legacy) call fails the test."""

    def _nope(*args, **kwargs):
        raise AssertionError("youtube-transcript-api must not be called")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", _nope)
    monkeypatch.setattr(cli.YouTubeTranscriptApi, "fetch", _nope, raising=False)
    monkeypatch.setattr(cli.YouTubeTranscriptApi, "list", _nope, raising=False)


def _marker_exists(transcripts_dir) -> bool:
    return Path(transcript_block.marker_path(str(transcripts_dir))).exists()


@pytest.fixture(autouse=True)
def _clean_memory_state():
    transcript_block._memory_state.clear()
    yield
    transcript_block._memory_state.clear()


# ---------------------------------------------------------------------------
# transcript_block module behavior
# ---------------------------------------------------------------------------


def test_not_blocked_without_marker(tmp_path):
    assert transcript_block.is_blocked(str(tmp_path), now=T0) is False
    assert transcript_block.blocked_until(str(tmp_path), now=T0) is None


def test_enter_block_sets_expiry_and_does_not_extend(tmp_path):
    marker = transcript_block.enter_block(
        str(tmp_path), duration_seconds=600, now=T0
    )
    assert marker["blocked_until"] == T0 + 600
    assert marker["duration_seconds"] == 600
    assert transcript_block.is_blocked(str(tmp_path), now=T0 + 300) is True

    # Already active: processing more videos must NOT extend the expiry.
    again = transcript_block.enter_block(
        str(tmp_path), duration_seconds=600, now=T0 + 300
    )
    assert again["blocked_until"] == T0 + 600


def test_is_blocked_respects_expiry(tmp_path):
    transcript_block.enter_block(str(tmp_path), duration_seconds=60, now=T0)
    assert transcript_block.is_blocked(str(tmp_path), now=T0 + 30) is True
    assert transcript_block.is_blocked(str(tmp_path), now=T0 + 61) is False
    assert transcript_block.blocked_until(str(tmp_path), now=T0 + 61) is None


def test_marker_persists_across_instances(tmp_path):
    """Persistence must survive process restart (fresh in-memory state)."""
    transcript_block.enter_block(str(tmp_path), duration_seconds=600, now=T0)
    transcript_block._memory_state.clear()  # simulate a fresh process
    assert transcript_block.is_blocked(str(tmp_path), now=T0 + 60) is True
    assert transcript_block.blocked_until(str(tmp_path), now=T0 + 60) == T0 + 600


def test_clear_block_removes_marker(tmp_path):
    transcript_block.enter_block(str(tmp_path), duration_seconds=600, now=T0)
    assert transcript_block.clear_block(str(tmp_path)) is True
    assert transcript_block.is_blocked(str(tmp_path), now=T0) is False


def test_corrupt_marker_is_not_blocked(tmp_path):
    Path(transcript_block.marker_path(str(tmp_path))).write_text(
        "{not json", encoding="utf-8"
    )
    assert transcript_block.is_blocked(str(tmp_path), now=T0) is False


def test_cooldown_duration_from_env(monkeypatch):
    monkeypatch.setenv(transcript_block.ENV_COOLDOWN_SECONDS, "1800")
    assert transcript_block.cooldown_seconds() == 1800


def test_cooldown_duration_from_config_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv(transcript_block.ENV_COOLDOWN_SECONDS, raising=False)
    cfg = {transcript_block.CONFIG_KEY_COOLDOWN_SECONDS: 900}
    assert transcript_block.cooldown_seconds(cfg) == 900
    assert (
        transcript_block.cooldown_seconds({})
        == transcript_block.DEFAULT_COOLDOWN_SECONDS
    )


def test_invalid_env_falls_back_to_default(monkeypatch, caplog):
    monkeypatch.setenv(transcript_block.ENV_COOLDOWN_SECONDS, "-5")
    with caplog.at_level(logging.WARNING, logger="ref_cli.transcript_block"):
        assert (
            transcript_block.cooldown_seconds()
            == transcript_block.DEFAULT_COOLDOWN_SECONDS
        )
    assert any(
        "Ignoring non-positive" in record.message
        for record in caplog.records
        if record.levelno == logging.WARNING
    )


def test_marker_file_is_nonsecret_json(tmp_path):
    marker = transcript_block.enter_block(str(tmp_path), duration_seconds=600, now=T0)
    raw = Path(transcript_block.marker_path(str(tmp_path))).read_text(
        encoding="utf-8"
    )
    data = json.loads(raw)
    assert data["blocked_until"] == marker["blocked_until"]
    for key in (
        "version",
        "blocked_until",
        "set_at",
        "duration_seconds",
        "lease_owner",
        "lease_expires_at",
        "next_probe_at",
    ):
        assert key in data
    assert "token" not in raw.lower()
    assert "secret" not in raw.lower()


def test_concurrent_enter_block_does_not_extend(tmp_path):
    """Multiple processes entering concurrently converge on one expiry."""
    results = []
    errors = []

    def worker():
        try:
            results.append(
                transcript_block.enter_block(
                    str(tmp_path), duration_seconds=600, now=T0
                )["blocked_until"]
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert results == [T0 + 600] * 8


def test_probe_guard_yields_false_when_blocked(tmp_path):
    transcript_block.enter_block(str(tmp_path), duration_seconds=600, now=T0)
    decision = transcript_block.begin_probe(str(tmp_path), now=T0 + 100)
    assert decision.allowed is False
    assert decision.message != ""
    assert decision.probing is False


def test_probe_guard_yields_true_when_not_blocked(tmp_path):
    decision = transcript_block.begin_probe(str(tmp_path), now=T0)
    assert decision.allowed is True
    assert decision.probing is False


# ---------------------------------------------------------------------------
# cli fetch path
# ---------------------------------------------------------------------------


def test_first_block_sets_cooldown_and_single_warning(monkeypatch, tmp_path, caplog):
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    calls = []

    def raise_blocked(*args, **kwargs):
        calls.append(args[0])
        raise RequestBlocked("YouTube is blocking requests from your IP.")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", raise_blocked)

    with caplog.at_level(logging.WARNING, logger="root"):
        result = cli.fetch_youtube_transcript(VIDEO_A)

    assert result[0] is None
    assert result[1][0] == "blocked"
    assert calls == [VIDEO_A]
    assert transcript_block.is_blocked(transcripts) is True
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "suppressing transcript fetches" in r.message
    ]
    assert len(warnings) == 1
    assert "3600 seconds" in warnings[0].message  # default cooldown


def test_second_video_during_cooldown_skips_provider(monkeypatch, tmp_path, caplog):
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    _block_provider(monkeypatch)
    transcript_block.enter_block(transcripts, duration_seconds=600)

    with caplog.at_level(logging.DEBUG, logger="root"):
        result = cli.fetch_youtube_transcript(VIDEO_B)

    assert result[0] is None
    assert result[1][0] == "blocked"
    assert "suppressed by IP cooldown" in result[1][1]
    # No repeated per-video IP-ban warning during an active cooldown.
    assert not any(
        r.levelno == logging.WARNING and "blocked transcript requests for" in r.message
        for r in caplog.records
    )
    # Only one transition warning total (from the setup enter_block); the skipped
    # video must not add any new "suppressing transcript fetches" warning.
    assert sum(
        1
        for r in caplog.records
        if r.levelno == logging.WARNING
        and "suppressing transcript fetches" in r.message
    ) == 1
    assert any(
        r.levelno == logging.DEBUG
        and "Transcript fetch skipped for" in r.message
        and "cooldown" in r.message
        for r in caplog.records
    )


def test_disk_transcript_reused_during_cooldown(monkeypatch, tmp_path):
    """Transcript already on disk is kept and NOT enqueued during cooldown."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / f"{VIDEO_A}.json").write_text(
        json.dumps({"transcript": "hello", "metadata": {}}), encoding="utf-8"
    )
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    _block_provider(monkeypatch)
    transcript_block.enter_block(str(transcripts), duration_seconds=600)

    result = cli.add_url_to_pending_file(VIDEO_URL_A, VIDEO_A)
    assert result.action == "skipped_on_disk"
    assert not pending.exists() or pending.read_text().strip() == ""


def test_cooldown_skip_still_queues_when_no_disk_transcript(monkeypatch, tmp_path):
    """Queue-first/local-transcribe path is preserved for cooldown skips."""
    transcripts = str(tmp_path / "transcripts")
    pending = str(tmp_path / "transcript-pending.md")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", pending)
    transcript_block.enter_block(transcripts, duration_seconds=600)

    def fake_enqueue(url, **kwargs):
        assert url == VIDEO_URL_A
        result = types.SimpleNamespace(
            kind="enqueued",
            source_key=f"youtube:{VIDEO_A}",
            execution=types.SimpleNamespace(execution_id="exec-cd-1", status="pending"),
            transcript_path=None,
        )
        return types.SimpleNamespace(
            result=result, fell_back_to_pending=False, error=None, pending_path=None
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)
    text = cli.resolve_transcript_failure_placeholder(
        ("blocked", "suppressed by IP cooldown"), VIDEO_URL_A, VIDEO_A
    )
    assert "queued for local-transcribe worker; execution exec-cd-1" in text


def test_cooldown_skip_falls_back_to_pending_file(monkeypatch, tmp_path):
    """When the queue is unavailable cooldown skips still use the pending file."""
    transcripts = str(tmp_path / "transcripts")
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    _force_legacy_pending(monkeypatch)
    transcript_block.enter_block(transcripts, duration_seconds=600)

    result = cli.add_url_to_pending_file(VIDEO_URL_A, VIDEO_A)
    assert result.action == "pending_file"
    assert "transcript-pending.md" in result.message
    assert VIDEO_URL_A in pending.read_text()


def test_expired_cooldown_allows_probe_and_success_clears(monkeypatch, tmp_path):
    """After expiry the next eligible fetch probes; success clears the marker."""
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    # Marker whose expiry has already passed (relative to wall clock).
    transcript_block.enter_block(
        str(transcripts), duration_seconds=60, now=time.time() - 100
    )
    assert transcript_block.is_blocked(str(transcripts), now=time.time()) is False

    calls = []

    def fake_success(video_id, save_to_file=False):
        calls.append(video_id)
        return {
            "transcript": "Hello",
            "duration": 1,
            "comments": [],
            "metadata": {"id": video_id, "title": "T", "channel": "C", "published_at": "D"},
        }

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", fake_success)

    transcript_file, failure_info = cli.fetch_youtube_transcript(
        VIDEO_A,
        metadata={"id": VIDEO_A, "title": "T", "channel": "C", "published_at": "D"},
    )

    assert transcript_file is not None
    assert failure_info is None
    assert calls == [VIDEO_A]
    assert transcript_block.is_blocked(str(transcripts), now=time.time()) is False
    assert not _marker_exists(transcripts)


def test_probe_reblock_renews_cooldown(monkeypatch, tmp_path):
    """A fresh probe that hits a confirmed block renews a fresh cooldown."""
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    transcript_block.enter_block(
        str(transcripts), duration_seconds=60, now=time.time() - 610
    )

    def raise_blocked(*args, **kwargs):
        raise RequestBlocked("YouTube is blocking requests from your IP.")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", raise_blocked)

    result = cli.fetch_youtube_transcript(VIDEO_A)

    assert result[0] is None
    assert result[1][0] == "blocked"
    deadline = transcript_block.blocked_until(str(transcripts), now=time.time())
    assert deadline is not None
    assert deadline > time.time() + 3000  # renewed towards now + default 3600


def test_no_false_trigger_on_unrelated_failure(monkeypatch, tmp_path, caplog):
    """A missing-captions (non-block) failure must not start a cooldown."""
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)

    def no_captions(*args, **kwargs):
        # Real library raises TranscriptsDisabled / NoTranscriptFound (not
        # RequestBlocked) for missing captions; both reach cli as generic
        # exceptions flagged with the "no transcript" phrase.
        raise Exception("No transcript available for video X: subtitles are disabled")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", no_captions)

    class _FakeYTTA:
        def fetch(self, *args, **kwargs):
            raise TranscriptsDisabled("Subtitles are disabled for this video")

        def list(self, *args, **kwargs):
            raise TranscriptsDisabled("Subtitles are disabled for this video")

    monkeypatch.setattr(cli, "YouTubeTranscriptApi", _FakeYTTA)

    with caplog.at_level(logging.WARNING, logger="root"):
        transcript_file, failure_info = cli.fetch_youtube_transcript(VIDEO_A)

    assert transcript_file is None
    assert failure_info is not None
    assert failure_info[0] != "blocked"
    # Not recognized as an IP block -> no cooldown marker is ever written.
    assert not _marker_exists(transcripts)
    assert not any(
        r.levelno == logging.WARNING and "suppressing transcript fetches" in r.message
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# API ingest path (service.process_one + HTTP endpoints)
# ---------------------------------------------------------------------------


def test_api_process_one_during_cooldown_returns_valid_result(monkeypatch, tmp_path):
    from ref_api import service
    from ref_cli import enrichment, youtube_extract

    transcripts = str(tmp_path / "transcripts")
    pending = tmp_path / "transcript-pending.md"
    references = tmp_path / "references.md"
    references.write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setattr(cli, "UNIFIED", str(references))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: False)
    monkeypatch.setattr(service.ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(
        service.ref_cli,
        "get_youtube_data",
        lambda url: (VIDEO_A, "Example Video", "Example Channel", "2026-01-01T00:00:00Z"),
    )
    _block_provider(monkeypatch)
    _force_legacy_pending(monkeypatch)
    # The fake video is not real; never let capture-time enrichment hit the
    # network or classify/drop the freshly appended row.
    monkeypatch.setattr(enrichment, "enrich_youtube_reference", lambda *a, **k: None)
    monkeypatch.setattr(
        youtube_extract,
        "read_video_card",
        lambda *a, **k: {"description": "", "source": "cache"},
    )

    transcript_block.enter_block(transcripts, duration_seconds=600)

    result = service.process_one(VIDEO_URL_A)

    assert result.status == "added"
    assert result.url == VIDEO_URL_A
    assert "suppressed by IP cooldown" in (result.output or "") or (
        "queued in transcript-pending.md" in (result.output or "")
    )
    assert VIDEO_URL_A in pending.read_text()
    assert VIDEO_URL_A in references.read_text()


def test_http_endpoints_healthy_during_cooldown(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from unittest.mock import patch

    from fastapi.testclient import TestClient
    from ref_api import service
    from ref_api.app import create_app
    from ref_cli import enrichment, youtube_extract

    transcripts = str(tmp_path / "transcripts")
    pending = tmp_path / "transcript-pending.md"
    references = tmp_path / "references.md"
    references.write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setattr(cli, "UNIFIED", str(references))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, config: False)
    monkeypatch.setattr(service.ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(
        service.ref_cli,
        "get_youtube_data",
        lambda url: (VIDEO_A, "Example Video", "Example Channel", "2026-01-01T00:00:00Z"),
    )
    _block_provider(monkeypatch)
    _force_legacy_pending(monkeypatch)
    monkeypatch.setattr(enrichment, "enrich_youtube_reference", lambda *a, **k: None)
    monkeypatch.setattr(
        youtube_extract,
        "read_video_card",
        lambda *a, **k: {"description": "", "source": "cache"},
    )

    transcript_block.enter_block(transcripts, duration_seconds=600)

    with patch("ref_api.app._bootstrap_archive"):
        with TestClient(create_app()) as client:
            health = client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            response = client.post("/urls", json={"url": VIDEO_URL_A})
            assert response.status_code == 200
            results = response.json()["results"]
            assert results[0]["status"] == "added"
            assert results[0]["input"] == VIDEO_URL_A

            # API remains available after the cooldown-skips ingest.
            health_after = client.get("/health")
            assert health_after.status_code == 200
            assert health_after.json()["status"] == "ok"
