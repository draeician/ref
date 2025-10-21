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
    assert "Transcript blocked by YouTube" in formatted
    assert "No transcript available" not in formatted


def test_get_youtube_transcript_with_metadata_rethrows_blocked(monkeypatch):
    def raise_blocked(*args, **kwargs):
        raise RequestBlocked("YouTube is blocking requests from your IP.")

    monkeypatch.setattr(
        get_transcript.YouTubeTranscriptApi,
        "get_transcript",
        staticmethod(raise_blocked),
        raising=False,
    )

    with pytest.raises(RequestBlocked) as excinfo:
        get_transcript.get_youtube_transcript_with_metadata("abcd1234567", save_to_file=False)

    assert "blocking transcript requests" in str(excinfo.value).lower()
    assert "github.com/jdepoix/youtube-transcript-api" in str(excinfo.value)
