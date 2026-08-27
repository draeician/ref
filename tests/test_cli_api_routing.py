"""Tests that ref CLI routes ingest/search through ref-api when configured."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ref_cli import cli


def test_run_ingest_uses_api_when_configured(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch("ref_cli.api_client.ingest_via_api", return_value=0) as mock_ingest:
        with pytest.raises(SystemExit) as exc:
            cli.run_ingest("https://example.com/a?x=1", force=True)
    assert exc.value.code == 0
    mock_ingest.assert_called_once_with(
        "http://127.0.0.1:8000", "https://example.com/a?x=1", force=True
    )


def test_run_search_uses_api_when_configured(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch("ref_cli.api_client.search_via_api", return_value=0) as mock_search:
        with pytest.raises(SystemExit) as exc:
            cli.run_search("example", field="title")
    assert exc.value.code == 0
    mock_search.assert_called_once_with(
        "http://127.0.0.1:8000", "example", field="title"
    )


def test_run_ingest_local_when_api_not_configured(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with patch("ref_cli.cli.process_url") as mock_process:
        cli.run_ingest("https://example.com", force=False)
    mock_process.assert_called_once_with("https://example.com", False)


def test_run_backup_uses_api_when_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: {"paths": {"references": str(tmp_path)}},
    )
    with patch("ref_cli.api_client.backup_via_api", return_value=0) as mock_backup:
        with pytest.raises(SystemExit) as exc:
            cli.run_backup(compress=True)
    assert exc.value.code == 0
    mock_backup.assert_called_once_with("http://127.0.0.1:8000", str(tmp_path), compress=True)


def test_run_file_ingest_uses_api_when_configured(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch("ref_cli.api_client.ingest_file_via_api") as mock_file:
        cli.run_file_ingest("/tmp/urls.txt", force=True)
    mock_file.assert_called_once_with("http://127.0.0.1:8000", "/tmp/urls.txt", force=True)


def test_run_transcript_uses_api_when_configured(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch("ref_cli.api_client.update_transcript_via_api", return_value=0) as mock_tx:
        with pytest.raises(SystemExit) as exc:
            cli.run_transcript("https://www.youtube.com/watch?v=abcd1234567")
    assert exc.value.code == 0
    mock_tx.assert_called_once_with(
        "http://127.0.0.1:8000",
        "https://www.youtube.com/watch?v=abcd1234567",
    )


def test_status_flag_exits_via_report(monkeypatch):
    args = type(
        "Args",
        (),
        {
            "status": True,
            "install_server": False,
            "uninstall_server": False,
            "server_status": False,
            "server_host": "0.0.0.0",
            "server_port": 8000,
            "verbose": False,
            "debug": None,
            "edit": False,
        },
    )()
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)
    monkeypatch.setattr(cli, "load_config", lambda: {"api_url": "http://minion:8000"})
    with patch("ref_cli.api_client.report_api_status", return_value=0) as mock_status:
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 0
    mock_status.assert_called_once_with({"api_url": "http://minion:8000"})
