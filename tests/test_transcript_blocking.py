import json
import logging
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest
from youtube_transcript_api._errors import RequestBlocked

from ref_cli import cli
import get_transcript

QUEUED_GENERIC = "Transcript unavailable (queued for local-transcribe)"
QUEUED_WORKER = (
    "Transcript unavailable (queued for local-transcribe worker; execution exec-1)"
)
ALREADY_QUEUED = (
    "Transcript unavailable (already in transcription queue: pending, execution exec-2)"
)
PENDING_FALLBACK_PREFIX = "Transcript unavailable (queue offline:"


def _install_fake_queue_api(monkeypatch, enqueue_fn):
    """Make ``from local_transcribe.queue_api import enqueue_youtube_safe`` work."""
    queue_api = types.ModuleType("local_transcribe.queue_api")
    queue_api.enqueue_youtube_safe = enqueue_fn
    lt = types.ModuleType("local_transcribe")
    lt.queue_api = queue_api
    monkeypatch.setitem(sys.modules, "local_transcribe", lt)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", queue_api)


def _block_local_transcribe(monkeypatch):
    """Force ImportError for local_transcribe (legacy pending-file path)."""
    monkeypatch.setitem(sys.modules, "local_transcribe", None)
    monkeypatch.setitem(sys.modules, "local_transcribe.queue_api", None)


def test_fetch_youtube_transcript_returns_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path))

    def raise_blocked(*args, **kwargs):
        raise RequestBlocked("YouTube is blocking requests from your IP.")

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", raise_blocked)

    transcript_file, failure_info = cli.fetch_youtube_transcript("abcd1234567")

    assert transcript_file is None
    assert failure_info is not None
    method, _ = failure_info
    assert method == "blocked"

    formatted = cli.format_transcript_failure(failure_info)
    assert QUEUED_GENERIC in formatted
    assert "No transcript available" not in formatted
    assert cli.should_queue_transcript_pending(failure_info)


def test_legacy_no_transcript_failure_queues_and_formats():
    failure_info = (
        "legacy",
        "Could not retrieve a transcript for the video! Subtitles are disabled for this video",
    )
    assert cli.is_no_transcript_failure(failure_info)
    assert cli.should_queue_transcript_pending(failure_info)
    formatted = cli.format_transcript_failure(failure_info)
    assert formatted == QUEUED_GENERIC
    assert "No transcript available" not in formatted


def test_enhanced_no_transcript_failure_queues():
    failure_info = (
        "enhanced",
        "No transcript available for video abcd1234567: subtitles are disabled",
    )
    assert cli.should_queue_transcript_pending(failure_info)
    assert cli.format_transcript_failure(failure_info) == QUEUED_GENERIC


def test_format_transcript_failure_uses_queue_message():
    failure_info = ("blocked", "IP blocked")
    assert (
        cli.format_transcript_failure(failure_info, queue_message=ALREADY_QUEUED)
        == ALREADY_QUEUED
    )


def test_rumble_failure_does_not_queue():
    failure_info = ("rumble", "Unable to download webpage: HTTP Error 403: Forbidden")
    assert not cli.should_queue_transcript_pending(failure_info)


def test_add_url_to_pending_skips_when_transcript_on_disk(monkeypatch, tmp_path):
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir()
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    (transcripts_dir / f"{video_id}.json").write_text(
        json.dumps({"transcript": "Hello world", "metadata": {}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(transcripts_dir))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    result = cli.add_url_to_pending_file(video_url, video_id)

    assert result.action == "skipped_on_disk"
    assert video_id in result.message
    assert not pending_file.exists() or pending_file.read_text().strip() == ""


def test_add_url_to_pending_enqueued(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    def fake_enqueue(url, **kwargs):
        assert url == video_url
        assert kwargs.get("origin") == "ref"
        assert kwargs.get("priority") == 20
        assert kwargs.get("pending_fallback") == pending_file
        execution = SimpleNamespace(execution_id="exec-1", status="pending")
        result = SimpleNamespace(
            kind="enqueued",
            source_key=f"youtube:{video_id}",
            execution=execution,
            transcript_path=None,
        )
        return SimpleNamespace(
            result=result,
            fell_back_to_pending=False,
            error=None,
            pending_path=None,
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "enqueued"
    assert outcome.execution_id == "exec-1"
    assert outcome.source_key == f"youtube:{video_id}"
    assert outcome.message == QUEUED_WORKER
    assert "transcript-pending.md" not in outcome.message
    assert not pending_file.exists()


def test_add_url_to_pending_existing_active(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    def fake_enqueue(url, **kwargs):
        execution = SimpleNamespace(execution_id="exec-2", status="pending")
        result = SimpleNamespace(
            kind="existing_active",
            source_key=f"youtube:{video_id}",
            execution=execution,
            transcript_path=None,
        )
        return SimpleNamespace(
            result=result,
            fell_back_to_pending=False,
            error=None,
            pending_path=None,
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "existing_active"
    assert outcome.execution_id == "exec-2"
    assert outcome.message == ALREADY_QUEUED
    assert "already in transcription queue" in outcome.message
    assert "transcript-pending.md" not in outcome.message
    assert not pending_file.exists()


def test_add_url_to_pending_queue_fallback(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    def fake_enqueue(url, **kwargs):
        # Simulate enqueue_youtube_safe writing the fallback itself
        pending_file.parent.mkdir(parents=True, exist_ok=True)
        pending_file.write_text(f"- {url}\n", encoding="utf-8")
        return SimpleNamespace(
            result=None,
            fell_back_to_pending=True,
            error="NFS mount missing",
            pending_path=pending_file,
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "pending_file"
    assert PENDING_FALLBACK_PREFIX in outcome.message
    assert "recorded in transcript-pending.md" in outcome.message
    assert "NFS mount missing" in outcome.message
    assert video_url in pending_file.read_text()


def test_add_url_to_pending_appends_new_url_when_api_missing(monkeypatch, tmp_path, capsys):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))
    monkeypatch.setattr(cli, "_local_transcribe_missing_notified", False)
    _block_local_transcribe(monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "pending_file"
    assert "local-transcribe not installed" in outcome.message
    assert "recorded in transcript-pending.md" in outcome.message
    assert pending_file.read_text().strip() == video_url
    printed = capsys.readouterr().out
    assert "pipx install" in printed
    assert "local_transcribe.git" in printed


def test_add_url_to_pending_via_lt_cli_when_import_missing(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))
    _block_local_transcribe(monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/lt" if name == "lt" else None)

    def fake_run(cmd, *args, **kwargs):
        assert cmd[:3] == ["/usr/bin/lt", "queue", "add"]
        assert "--origin" in cmd and "ref" in cmd
        assert "--priority" in cmd and "20" in cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=(
                f"enqueued: youtube:{video_id}\n"
                "  execution_id=exec-cli-1\n"
                f"  source_key=youtube:{video_id}\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "enqueued"
    assert outcome.execution_id == "exec-cli-1"
    assert "queued for local-transcribe worker" in outcome.message
    assert "transcript-pending.md" not in outcome.message
    assert not pending_file.exists()


def test_add_url_to_pending_dedupes_existing_url(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    pending_file.write_text(f"{video_url}\n", encoding="utf-8")

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))
    _block_local_transcribe(monkeypatch)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    outcome = cli.add_url_to_pending_file(video_url, video_id)

    assert outcome.action == "pending_file"
    assert pending_file.read_text().count(video_url) == 1


def test_resolve_placeholder_uses_enqueue_message(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    def fake_enqueue(url, **kwargs):
        execution = SimpleNamespace(execution_id="exec-2", status="processing")
        result = SimpleNamespace(
            kind="existing_active",
            source_key=f"youtube:{video_id}",
            execution=execution,
            transcript_path=None,
        )
        return SimpleNamespace(
            result=result,
            fell_back_to_pending=False,
            error=None,
            pending_path=None,
        )

    _install_fake_queue_api(monkeypatch, fake_enqueue)

    text = cli.resolve_transcript_failure_placeholder(
        ("blocked", "blocked"), video_url, video_id
    )
    assert "already in transcription queue: processing, execution exec-2" in text
    assert "transcript-pending.md" not in text


def test_get_youtube_transcript_with_metadata_rethrows_blocked(monkeypatch):
    def raise_blocked(*args, **kwargs):
        raise RequestBlocked("YouTube is blocking requests from your IP.")

    monkeypatch.setattr(
        get_transcript.YouTubeTranscriptApi,
        "fetch",
        raise_blocked,
        raising=False,
    )

    with pytest.raises(RequestBlocked) as excinfo:
        get_transcript.get_youtube_transcript_with_metadata("abcd1234567", save_to_file=False)

    assert "blocking transcript requests" in str(excinfo.value).lower()
    assert "github.com/jdepoix/youtube-transcript-api" in str(excinfo.value)


def test_rumble_403_transcript_failure_records_without_error_logs(monkeypatch, tmp_path, caplog, capsys):
    rumble_url = "https://rumble.com/v765j42-the-human-antenna-doco.html?e9s=src_v1_eh_cs"
    references_file = tmp_path / "references.md"
    references_file.write_text("")

    monkeypatch.setattr(cli, "UNIFIED", str(references_file))
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "load_config", lambda: {})

    html = (
        '<html><head><meta property="og:title" '
        'content="The Human Antenna Documentary"/></head><body></body></html>'
    )
    stderr = (
        "ERROR: [Rumble] v765j42-the-human-antenna-doco: "
        "Unable to download webpage: HTTP Error 403: Forbidden"
    )

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:2] == ["which", "lynx"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if isinstance(cmd, str) and "lynx" in cmd:
            return subprocess.CompletedProcess(cmd, 0, html, "")
        if isinstance(cmd, list) and cmd and cmd[0] == "yt-dlp" and "--dump-json" in cmd:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr=stderr)
        raise AssertionError(f"unexpected subprocess.run: {cmd!r}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG)

    cli.process_url(rumble_url, force=False)

    output = capsys.readouterr().out
    assert "|(The Human Antenna Documentary)|Rumble|General|No transcript available" in output
    assert "|(The Human Antenna Documentary)|Rumble|General|No transcript available" in references_file.read_text()
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_unexpected_rumble_video_info_failure_still_logs_error(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "load_config", lambda: {})

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd and cmd[0] == "yt-dlp" and "--dump-json" in cmd:
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="ERROR: extractor crashed")
        raise AssertionError(f"unexpected subprocess.run: {cmd!r}")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    caplog.set_level(logging.DEBUG)

    transcript_file, failure_info = cli.fetch_youtube_transcript("https://rumble.com/v765j42.html")

    assert transcript_file is None
    assert failure_info is not None
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
