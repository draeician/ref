"""Regression tests for channel/profile URLs redirected from YouTube show notes."""

import pytest

from ref_cli import cli


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/channel/UCzw2KK537iRgsrYnWaEMs8Q?sub_confirmation=1",
        "https://youtube.com/@kurzgesagt",
        "https://m.youtube.com/c/ExampleChannel",
        "https://youtube.com/user/ExampleAccount",
    ],
)
def test_youtube_channel_shapes(url):
    assert cli._is_youtube_channel_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=PqtggjVAi8M",
        "https://www.youtube.com/shorts/PqtggjVAi8M",
        "https://www.youtube.com/live/PqtggjVAi8M",
        "https://www.youtube.com/playlist?list=PL123",
        "https://youtube.com.evil.example/channel/fake",
        "https://www.youtube.com/post/Ugkx123",
    ],
)
def test_non_channel_urls_not_misclassified(url):
    assert not cli._is_youtube_channel_url(url)


def test_redirect_to_channel_uses_general_archive_path(monkeypatch):
    """The API ingest path resolves short links before dispatching."""
    original = "https://kgs.link/youtubeDE"
    destination = (
        "https://www.youtube.com/channel/UCzw2KK537iRgsrYnWaEMs8Q"
        "?sub_confirmation=1"
    )
    calls = []
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: destination)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)
    monkeypatch.setattr(
        cli, "_record_general_url",
        lambda url, force, now: calls.append((url, force))
    )
    monkeypatch.setattr(
        cli, "get_youtube_data",
        lambda url: pytest.fail("channel URL was routed into video lookup")
    )

    cli.process_url(original, False)
    assert calls == [(destination, False)]


def test_general_channel_archiving_writes_reference(monkeypatch):
    """Channel destinations are persisted by the existing general URL writer."""
    url = "https://www.youtube.com/channel/UCzw2KK537iRgsrYnWaEMs8Q"
    lines = []
    monkeypatch.setattr(cli, "get_title_from_url", lambda url: "Kurzgesagt")
    monkeypatch.setattr(cli, "url_exists_in_file", lambda *args: False)
    monkeypatch.setattr(cli, "_append_reference_line", lines.append)
    cli._record_general_url(url, False, "2026-10-10T12:00:00")
    assert lines == [
        "2026-10-10T12:00:00|"
        f"[{url}]|(Kurzgesagt)|General|General\n"
    ]
