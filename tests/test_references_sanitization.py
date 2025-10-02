import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


from ref_cli import cli as cli_module


def test_update_reference_entry_strips_prompt_noise(tmp_path, monkeypatch):
    references_path = tmp_path / "references.md"
    references_path.write_text(
        "2024-01-01T00:00:00|[https://example.com]|(Example)|Uploader|YouTube|None\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(cli_module, "UNIFIED", str(references_path))

    failure_info = (
        "yt_dlp",
        "Enter a URL or YouTube video ID to record\nYouTube is blocking requests from your IP\nDetailed failure message",
    )
    failure_string = cli_module.format_transcript_failure(failure_info)

    cli_module.update_reference_entry(
        "https://example.com",
        "Example",
        "Uploader",
        failure_string,
    )

    updated_line = references_path.read_text(encoding="utf-8").strip()

    assert "Enter a URL or YouTube video ID to record" not in updated_line
    assert "YouTube is blocking requests from your IP" not in updated_line
    assert updated_line.endswith(
        "|No transcript available (Yt Dlp method: Detailed failure message)"
    )
