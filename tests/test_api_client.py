"""Tests for ref CLI HTTP client helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

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


def test_format_http_error_html_403_no_html_dump():
    response = MagicMock()
    response.status_code = 403
    response.headers = {"content-type": "text/html"}
    response.text = (
        "<!DOCTYPE html><html><body><pre>Forbidden</pre></body></html>"
    )
    response.reason = "Forbidden"
    response.json.side_effect = ValueError("no json")

    message = api_client._format_http_error("http://nomnom:8000", response)
    assert "nomnom:8000" in message
    assert "403" in message
    assert "HTML" in message
    assert "api_url" in message
    assert "<!DOCTYPE" not in message
    assert "Forbidden</pre>" not in message


def test_format_connection_refused():
    exc = requests.exceptions.ConnectionError(
        "HTTPConnectionPool(host='minion', port=8000): "
        "Max retries exceeded with url: /urls "
        "(Caused by NewConnectionError("
        "\"<urllib3.connection.HTTPConnection object>: "
        "Failed to establish a new connection: [Errno 111] Connection refused\"))"
    )
    message = api_client._format_connection_error("http://minion:8000", exc)
    assert "minion:8000" in message
    assert "Connection refused" in message or "connection refused" in message.lower()
    assert "api_url" in message


def test_format_dns_failure():
    exc = requests.exceptions.ConnectionError(
        "Failed to resolve 'badhost' ([Errno -2] Name or service not known)"
    )
    message = api_client._format_connection_error("http://badhost:8000", exc)
    assert "badhost:8000" in message
    assert "resolve" in message.lower()


def test_request_json_uses_friendly_http_error():
    response = MagicMock()
    response.status_code = 403
    response.headers = {"content-type": "text/html"}
    response.text = "<html>Forbidden</html>"
    response.reason = "Forbidden"
    response.json.side_effect = ValueError("no json")

    with patch("ref_cli.api_client.requests.request", return_value=response):
        with pytest.raises(api_client.ApiError) as excinfo:
            api_client._request_json(
                "POST",
                "http://nomnom:8000",
                "/urls",
                timeout=5,
                json_body={"url": "https://example.com"},
            )
    assert "nomnom:8000" in str(excinfo.value)
    assert "<html>" not in str(excinfo.value)


def test_report_api_status_local_mode(capsys):
    code = api_client.report_api_status({})
    out = capsys.readouterr().out
    assert code == 0
    assert "local" in out.lower()
    assert "api_url not set" in out


def test_report_api_status_healthy(capsys):
    with patch(
        "ref_cli.api_client.check_health",
        return_value={"status": "ok", "version": "1.6.12"},
    ):
        code = api_client.report_api_status({"api_url": "http://minion:8000"})
    out = capsys.readouterr().out
    assert code == 0
    assert "remote" in out.lower()
    assert "minion:8000" in out
    assert "ok" in out.lower()
    assert "1.6.12" in out


def test_report_api_status_unreachable(capsys):
    with patch(
        "ref_cli.api_client.check_health",
        side_effect=api_client.ApiError(
            "Connection refused to ref API at nomnom:8000 "
            "(nothing accepting connections on that host/port)."
        ),
    ):
        code = api_client.report_api_status({"api_url": "http://nomnom:8000"})
    out = capsys.readouterr().out
    assert code == 1
    assert "unreachable" in out.lower()
    assert "nomnom:8000" in out


def test_check_health_calls_endpoint():
    with patch(
        "ref_cli.api_client._request_json",
        return_value={"status": "ok", "version": "1.0"},
    ) as mock_req:
        body = api_client.check_health("http://minion:8000")
    assert body["status"] == "ok"
    mock_req.assert_called_once_with(
        "GET",
        "http://minion:8000",
        "/health",
        timeout=api_client.DEFAULT_HEALTH_TIMEOUT,
    )


def test_search_via_api_success(capsys):
    mock_response = [{"line": "row\n", "hit_types": ["Title"]}]
    with patch("ref_cli.api_client.search_refs", return_value=mock_response):
        code = api_client.search_via_api("http://127.0.0.1:8000", "term")
    assert code == 0
    assert "-Hit Type: Title" in capsys.readouterr().out


def test_list_via_api_success(capsys):
    with patch(
        "ref_cli.api_client.list_refs",
        return_value=["https://example.com/a", "https://example.com/b"],
    ) as mock_list:
        code = api_client.list_via_api("http://127.0.0.1:8000", limit=2)
    assert code == 0
    mock_list.assert_called_once_with(
        "http://127.0.0.1:8000", limit=2, since=None
    )
    assert capsys.readouterr().out.strip().splitlines() == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_list_via_api_error(capsys):
    with patch(
        "ref_cli.api_client.list_refs",
        side_effect=api_client.ApiError("bad duration", status_code=400),
    ):
        code = api_client.list_via_api("http://127.0.0.1:8000", since="fortnight")
    assert code == 1
    assert "bad duration" in capsys.readouterr().out


def test_list_refs_calls_endpoint():
    with patch(
        "ref_cli.api_client._request_json",
        return_value={"urls": ["https://example.com"]},
    ) as mock_req:
        urls = api_client.list_refs("http://minion:8000", since="5 min")
    assert urls == ["https://example.com"]
    mock_req.assert_called_once_with(
        "GET",
        "http://minion:8000",
        "/list",
        timeout=api_client.DEFAULT_SEARCH_TIMEOUT,
        params={"since": "5 min"},
    )


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
    assert not (tmp_path / "20260101T120000_references.md.gz.partial").exists()


def test_api_base_is_local_loopback():
    assert api_client.api_base_is_local("http://127.0.0.1:8000")
    assert api_client.api_base_is_local("http://localhost:8000")
    assert not api_client.api_base_is_local("http://archive.example:8000")


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
