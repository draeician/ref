import logging
import subprocess

import pytest
from youtube_transcript_api._errors import RequestBlocked

from ref_cli import cli
import get_transcript


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
    assert "Transcript unavailable (queued in transcript-pending.md)" in formatted
    assert "No transcript available" not in formatted


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
