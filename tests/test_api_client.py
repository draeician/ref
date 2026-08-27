"""Tests for ref CLI HTTP client helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ref_cli import api_client


def test_get_api_base_url_from_config():
    assert (
        api_client.get_api_base_url({"api_url": "http://127.0.0.1:8000/"})
        == "http://127.0.0.1:8000"
    )
    assert api_client.get_api_base_url({"api_url": None}) is None
    assert api_client.get_api_base_url({}) is None


def test_get_api_base_url_env_override(monkeypatch):
    monkeypatch.setenv("REF_API_URL", "http://api.example:9000")
    assert (
        api_client.get_api_base_url({"api_url": "http://ignored:1"})
        == "http://api.example:9000"
    )


def test_print_ingest_results_added(capsys):
    code = api_client.print_ingest_results(
        [
            {
                "input": "https://example.com",
                "url": "https://example.com",
                "status": "added",
                "output": "2026-01-01T00:00:00|[https://example.com]|(Title)|General|General",
            }
        ]
    )
    captured = capsys.readouterr().out
    assert "2026-01-01T00:00:00" in captured
    assert code == 0


def test_print_ingest_results_error(capsys):
    code = api_client.print_ingest_results(
        [
            {
                "input": "https://bad.example",
                "url": "https://bad.example",
                "status": "error",
                "output": "Error: dead link",
            }
        ]
    )
    assert "Error: dead link" in capsys.readouterr().out
    assert code == 1


def test_print_ingest_results_skipped(capsys):
    code = api_client.print_ingest_results(
        [
            {
                "input": "https://mail.google.com/",
                "url": "https://mail.google.com/",
                "status": "skipped",
                "message": "Matches skip pattern",
            }
        ]
    )
    assert "Skipping URL" in capsys.readouterr().out
    assert code == 0


def test_print_search_results(capsys):
    api_client.print_search_results(
        [{"line": "2026-01-01|[https://x]|(t)|a|b\n", "hit_types": ["Url", "Title"]}]
    )
    out = capsys.readouterr().out
    assert "2026-01-01|[https://x]|(t)|a|b" in out
    assert "-Hit Type: Url" in out
    assert "-Hit Type: Title" in out


def test_ingest_via_api_connection_error(capsys):
    with patch("ref_cli.api_client.ingest_urls", side_effect=api_client.ApiError("down")):
        code = api_client.ingest_via_api("http://127.0.0.1:8000", "https://example.com")
    assert code == 1
    assert "down" in capsys.readouterr().out


def test_search_via_api_success(capsys):
    mock_response = [{"line": "row\n", "hit_types": ["Title"]}]
    with patch("ref_cli.api_client.search_refs", return_value=mock_response):
        code = api_client.search_via_api("http://127.0.0.1:8000", "term")
    assert code == 0
    assert "-Hit Type: Title" in capsys.readouterr().out


def test_download_backup_writes_file(tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {
        "content-disposition": 'attachment; filename="20260101T120000_references.md.gz"'
    }
    mock_response.iter_content = lambda chunk_size: [b"backup-bytes"]

    with patch("ref_cli.api_client.requests.post", return_value=mock_response):
        path = api_client.download_backup(
            "http://127.0.0.1:8000",
            str(tmp_path),
            compress=True,
        )

    assert path.endswith("20260101T120000_references.md.gz")
    assert (tmp_path / "20260101T120000_references.md.gz").read_bytes() == b"backup-bytes"


def test_backup_via_api_success(capsys, tmp_path):
    with patch(
        "ref_cli.api_client.download_backup",
        return_value=str(tmp_path / "20260101T120000_references.md.gz"),
    ):
        code = api_client.backup_via_api(
            "http://127.0.0.1:8000",
            str(tmp_path),
            compress=True,
        )
    assert code == 0
    assert "Backup downloaded" in capsys.readouterr().out


def test_update_transcript_via_api(capsys):
    payload = {
        "result": {
            "url": "https://www.youtube.com/watch?v=abcd1234567",
            "status": "updated",
            "output": "Transcript for https://www.youtube.com/watch?v=abcd1234567 has been updated.",
        }
    }
    with patch("ref_cli.api_client._request_json", return_value=payload):
        code = api_client.update_transcript_via_api(
            "http://127.0.0.1:8000",
            "https://www.youtube.com/watch?v=abcd1234567",
        )
    assert code == 0
    assert "has been updated" in capsys.readouterr().out


def test_ingest_file_via_api_comments_processed_lines(tmp_path, monkeypatch):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://example.com/one\nhttps://example.com/two\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ref_cli.cli.should_skip_url",
        lambda _url, _cfg: False,
    )
    with (
        patch(
            "ref_cli.api_client.ingest_urls",
            return_value=[
                {
                    "input": "https://example.com/one",
                    "url": "https://example.com/one",
                    "status": "added",
                    "output": "added-line",
                }
            ],
        ) as mock_ingest,
        patch("time.sleep"),
    ):
        api_client.ingest_file_via_api("http://127.0.0.1:8000", str(urls_file))

    assert mock_ingest.call_count == 2
    text = urls_file.read_text(encoding="utf-8")
    assert text.startswith("# https://example.com/one")
    assert "# https://example.com/two" in text
