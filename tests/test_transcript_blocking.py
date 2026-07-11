import json
import logging
import subprocess

import pytest
from youtube_transcript_api._errors import RequestBlocked

from ref_cli import cli
import get_transcript

QUEUED_MESSAGE = "Transcript unavailable (queued in transcript-pending.md)"


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
    assert QUEUED_MESSAGE in formatted
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
    assert formatted == QUEUED_MESSAGE
    assert "No transcript available" not in formatted


def test_enhanced_no_transcript_failure_queues():
    failure_info = (
        "enhanced",
        "No transcript available for video abcd1234567: subtitles are disabled",
    )
    assert cli.should_queue_transcript_pending(failure_info)
    assert cli.format_transcript_failure(failure_info) == QUEUED_MESSAGE


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

    cli.add_url_to_pending_file(video_url, video_id)

    assert not pending_file.exists() or pending_file.read_text().strip() == ""


def test_add_url_to_pending_appends_new_url(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    cli.add_url_to_pending_file(video_url, video_id)

    assert pending_file.read_text().strip() == video_url


def test_add_url_to_pending_dedupes_existing_url(monkeypatch, tmp_path):
    pending_file = tmp_path / "transcript-pending.md"
    video_id = "abcd1234567"
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    pending_file.write_text(f"{video_url}\n", encoding="utf-8")

    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts"))
    monkeypatch.setattr(cli, "TRANSCRIPT_PENDING_FILE", str(pending_file))

    cli.add_url_to_pending_file(video_url, video_id)

    assert pending_file.read_text().count(video_url) == 1


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
