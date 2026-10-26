import json
import logging
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from ref_cli import cli, transcript_queue

VIDEO_ID = "abcd1234567"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
QUEUE_UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def _isolate_transcript_env(monkeypatch, tmp_path):
    for name in (
        transcript_queue.ENV_MODE,
        transcript_queue.ENV_LT_PATH,
        transcript_queue.ENV_QUEUE_DIR,
        transcript_queue.ENV_QUEUE_UUID,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "CONFIG_FILE", str(tmp_path / "missing-config.yaml"))


def _forbid_remote(monkeypatch):
    calls = []

    def nope(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("remote transcript retrieval must not be called")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", nope)
    monkeypatch.setattr(cli.YouTubeTranscriptApi, "fetch", nope, raising=False)
    monkeypatch.setattr(cli.YouTubeTranscriptApi, "list", nope, raising=False)
    return calls


def _write_transcript(directory: Path, video_id: str = VIDEO_ID) -> Path:
    path = directory / f"{video_id}.json"
    path.write_text(
        json.dumps({"transcript": "existing text", "metadata": {"id": video_id}}),
        encoding="utf-8",
    )
    return path


def _install_fake_queue_api(monkeypatch, enqueue_fn):
    queue_api = types.ModuleType("local_transcribe.queue_api")
    queue_api.enqueue_youtube_safe = enqueue_fn
    local_transcribe = types.ModuleType("local_transcribe")
    local_transcribe.queue_api = queue_api
    monkeypatch.setitem(sys.modules, "local_transcribe", local_transcribe)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", queue_api)


def _block_python_queue_api(monkeypatch):
    monkeypatch.setitem(sys.modules, "local_transcribe", None)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", None)


def _make_queue(tmp_path: Path, uuid: str = QUEUE_UUID) -> Path:
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    (queue_dir / "queue.id").write_text(
        json.dumps({"queue_uuid": uuid}), encoding="utf-8"
    )
    return queue_dir


def _make_lt(tmp_path: Path) -> Path:
    lt_path = tmp_path / "lt"
    lt_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    lt_path.chmod(0o755)
    return lt_path


def _enqueued_outcome(execution_id: str = "exec-1") -> SimpleNamespace:
    execution = SimpleNamespace(execution_id=execution_id, status="pending")
    result = SimpleNamespace(
        kind="enqueued",
        source_key=f"youtube:{VIDEO_ID}",
        execution=execution,
        transcript_path=None,
    )
    return SimpleNamespace(
        result=result,
        fell_back_to_pending=False,
        error=None,
        pending_path=None,
    )


def test_local_only_reuses_existing_transcript_without_remote(
    monkeypatch, tmp_path
):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    existing = _write_transcript(transcripts)
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    monkeypatch.setenv(transcript_queue.ENV_MODE, transcript_queue.MODE_LOCAL_ONLY)
    calls = _forbid_remote(monkeypatch)

    transcript_file, failure_info = cli.fetch_youtube_transcript(VIDEO_ID)

    assert transcript_file == str(existing)
    assert failure_info is None
    assert calls == []
    assert not (transcripts / ".youtube-transcript-block.json").exists()


def test_local_only_missing_transcript_skips_remote_and_labels_status(
    monkeypatch, tmp_path, caplog
):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    monkeypatch.setenv(transcript_queue.ENV_MODE, transcript_queue.MODE_LOCAL_ONLY)
    calls = _forbid_remote(monkeypatch)

    with caplog.at_level(logging.INFO, logger="root"):
        transcript_file, failure_info = cli.fetch_youtube_transcript(VIDEO_ID)

    assert transcript_file is None
    assert failure_info is not None
    assert failure_info[0] == "local_only"
    assert cli.should_queue_transcript_pending(failure_info)
    assert calls == []
    assert any("intentionally skipped" in r.message for r in caplog.records)
    formatted = cli.format_transcript_failure(failure_info)
    assert formatted == (
        "Transcript unavailable (local-only mode; queued for local-transcribe)"
    )


def test_local_only_does_not_modify_cooldown_marker(monkeypatch, tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    marker = transcripts / ".youtube-transcript-block.json"
    original = json.dumps(
        {
            "blocked_until": 9999999999.0,
            "set_at": 1.0,
            "duration_seconds": 3600,
            "lease_owner": None,
            "lease_expires_at": 0.0,
            "next_probe_at": 0.0,
            "version": 1,
        }
    ).encode("utf-8")
    marker.write_bytes(original)
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    monkeypatch.setenv(transcript_queue.ENV_MODE, transcript_queue.MODE_LOCAL_ONLY)
    calls = _forbid_remote(monkeypatch)

    transcript_file, failure_info = cli.fetch_youtube_transcript(VIDEO_ID)

    assert transcript_file is None
    assert failure_info is not None and failure_info[0] == "local_only"
    assert calls == []
    assert marker.read_bytes() == original


def test_local_only_resolve_message_keeps_queue_execution_id(monkeypatch, tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    _install_fake_queue_api(
        monkeypatch,
        lambda url, **kwargs: _enqueued_outcome("exec-local-only"),
    )

    text = cli.resolve_transcript_failure_placeholder(
        ("local_only", "remote retrieval intentionally skipped"),
        VIDEO_URL,
        VIDEO_ID,
    )

    assert text.startswith("Transcript unavailable (local-only mode;")
    assert "queued for local-transcribe worker; execution exec-local-only" in text
    assert "transcript-pending.md" not in text
    assert not pending.exists()


def test_remote_first_default_calls_provider(monkeypatch, tmp_path):
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts))
    calls = []

    def fake_provider(video_id, save_to_file=False):
        calls.append(video_id)
        return {
            "transcript": "remote text",
            "duration": 1,
            "comments": [],
            "metadata": {"id": video_id},
        }

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", fake_provider)

    transcript_file, failure_info = cli.fetch_youtube_transcript(VIDEO_ID)

    assert calls == [VIDEO_ID]
    assert transcript_file == str(transcripts / f"{VIDEO_ID}.json")
    assert failure_info is None


def test_invalid_mode_falls_back_to_remote_first(monkeypatch, caplog):
    monkeypatch.setenv(transcript_queue.ENV_MODE, "invalid-mode")
    with caplog.at_level(logging.WARNING, logger="ref_cli.transcript_queue"):
        assert transcript_queue.resolve_mode({}) == transcript_queue.MODE_REMOTE_FIRST
    assert any("Ignoring invalid" in record.message for record in caplog.records)


def test_config_key_supports_local_only():
    assert (
        transcript_queue.resolve_mode({"youtube_transcript_mode": "local_only"})
        == transcript_queue.MODE_LOCAL_ONLY
    )


def test_relative_explicit_paths_are_rejected():
    with pytest.raises(transcript_queue.TranscriptQueueConfigError):
        transcript_queue.resolve_lt_path({"local_transcribe_lt": "lt"})
    with pytest.raises(transcript_queue.TranscriptQueueConfigError):
        transcript_queue.resolve_queue_dir({"local_transcribe_queue_dir": "queue"})


def test_explicit_lt_and_queue_dir_enqueue_with_execution_id(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    lt_path = _make_lt(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_LT_PATH, str(lt_path))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_UUID, QUEUE_UUID)
    _block_python_queue_api(monkeypatch)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                f"enqueued: youtube:{VIDEO_ID}\n"
                "  execution_id=exec-cli-1\n"
                f"  source_key=youtube:{VIDEO_ID}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "enqueued"
    assert outcome.execution_id == "exec-cli-1"
    assert outcome.source_key == f"youtube:{VIDEO_ID}"
    assert "queued for local-transcribe worker" in outcome.message
    assert "transcript-pending.md" not in outcome.message
    assert not pending.exists()
    assert calls
    cmd, kwargs = calls[0]
    assert cmd[:4] == [str(lt_path), "queue", "add", VIDEO_URL]
    assert "--queue-dir" in cmd
    assert cmd[cmd.index("--queue-dir") + 1] == str(queue_dir)
    assert kwargs.get("shell") is not True


def test_explicit_lt_duplicate_existing_active_is_reported(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    lt_path = _make_lt(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_LT_PATH, str(lt_path))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_UUID, QUEUE_UUID)
    _block_python_queue_api(monkeypatch)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                f"existing_active: youtube:{VIDEO_ID}\n"
                "  execution_id=exec-cli-2\n"
                f"  source_key=youtube:{VIDEO_ID}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "existing_active"
    assert outcome.execution_id == "exec-cli-2"
    assert "already in transcription queue" in outcome.message
    assert "transcript-pending.md" not in outcome.message
    assert not pending.exists()


def test_missing_lt_executable_falls_back_to_pending(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    missing_lt = tmp_path / "missing-lt"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_LT_PATH, str(missing_lt))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    _block_python_queue_api(monkeypatch)

    def fail_run(*args, **kwargs):
        raise AssertionError("lt must not run when configured path is missing")

    monkeypatch.setattr(cli.subprocess, "run", fail_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "pending_file"
    assert "lt executable unavailable" in outcome.message
    assert "transcript-pending.md" in outcome.message
    assert "queued for local-transcribe worker" not in outcome.message
    assert pending.read_text(encoding="utf-8").strip() == VIDEO_URL


def test_wrong_queue_uuid_falls_back_to_pending(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    lt_path = _make_lt(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_LT_PATH, str(lt_path))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_UUID, "wrong-uuid")
    _block_python_queue_api(monkeypatch)

    def fail_run(*args, **kwargs):
        raise AssertionError("lt must not run when queue identity is wrong")

    monkeypatch.setattr(cli.subprocess, "run", fail_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "pending_file"
    assert "Queue UUID mismatch" in outcome.message
    assert "transcript-pending.md" in outcome.message
    assert pending.read_text(encoding="utf-8").strip() == VIDEO_URL


def test_unavailable_queue_dir_falls_back_to_pending(monkeypatch, tmp_path):
    pending = tmp_path / "transcript-pending.md"
    missing_queue = tmp_path / "missing-queue"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(missing_queue))
    _block_python_queue_api(monkeypatch)

    def fail_run(*args, **kwargs):
        raise AssertionError("lt must not run when queue is unavailable")

    monkeypatch.setattr(cli.subprocess, "run", fail_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "pending_file"
    assert "Queue directory does not exist" in outcome.message
    assert "transcript-pending.md" in outcome.message
    assert pending.read_text(encoding="utf-8").strip() == VIDEO_URL


def test_python_queue_api_receives_configured_queue_dir(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_UUID, QUEUE_UUID)
    seen = {}

    def fake_enqueue(url, **kwargs):
        seen.update(kwargs)
        return _enqueued_outcome("exec-api-1")

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "enqueued"
    assert outcome.execution_id == "exec-api-1"
    assert seen["queue_dir"] == queue_dir
    assert seen["origin"] == "ref"
    assert seen["priority"] == 20
    assert seen["pending_fallback"] == pending
    assert not pending.exists()


def test_python_queue_api_none_result_writes_pending(monkeypatch, tmp_path):
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))

    def fake_enqueue(url, **kwargs):
        return SimpleNamespace(
            result=None,
            fell_back_to_pending=False,
            error=None,
            pending_path=None,
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "pending_file"
    assert "transcript-pending.md" in outcome.message
    assert "queued for local-transcribe worker" not in outcome.message
    assert pending.read_text(encoding="utf-8").strip() == VIDEO_URL


def test_pending_fallback_write_failure_is_not_reported_as_recorded(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(cli, "_append_url_to_pending_file", lambda url: False)

    outcome = cli._pending_file_fallback_result(
        VIDEO_URL, failure_reason="local-only mode"
    )

    assert outcome.action == "pending_file_failed"
    assert "transcript-pending.md could not be updated" in outcome.message
    assert "recorded in transcript-pending.md" not in outcome.message
    assert "local-only mode" in outcome.message


def test_lt_cli_parser_ignores_warning_lines(monkeypatch, tmp_path):
    queue_dir = _make_queue(tmp_path)
    lt_path = _make_lt(tmp_path)
    pending = tmp_path / "transcript-pending.md"
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending))
    monkeypatch.setenv(transcript_queue.ENV_LT_PATH, str(lt_path))
    monkeypatch.setenv(transcript_queue.ENV_QUEUE_DIR, str(queue_dir))
    _block_python_queue_api(monkeypatch)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                "\x1b[33mWarning: Deno runtime not detected\x1b[0m\n"
                f"\x1b[32menqueued\x1b[0m: youtube:{VIDEO_ID}\n"
                "  \x1b[36mexecution_id=exec-warning-1\x1b[0m\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    outcome = cli.add_url_to_pending_file(VIDEO_URL, VIDEO_ID)

    assert outcome.action == "enqueued"
    assert outcome.execution_id == "exec-warning-1"
