"""Regression tests for the remote-client execution path.

These tests simulate a client host with no archive, no Google credentials, and
no worker dependencies. A normal CLI ingest/search/transcript/file operation
must go through ref-api or print setup guidance; it must never bootstrap or
write the local archive and never call Google metadata directly.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ref_cli import cli


def _args(**overrides):
    values = {
        "status": False,
        "upgrade": False,
        "install_server": False,
        "uninstall_server": False,
        "server_status": False,
        "server_host": "0.0.0.0",
        "server_port": 8000,
        "url": None,
        "force": False,
        "edit": False,
        "debug": None,
        "verbose": False,
        "integrity": False,
        "backup": False,
        "nocompress": False,
        "list": None,
        "search": None,
        "search_url": None,
        "search_title": None,
        "search_date": None,
        "search_source": None,
        "search_uploader": None,
        "url_dump": None,
        "transcript": False,
        "file": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _restore_root_log_level():
    """``main`` adjusts the root level; do not leak it into later tests."""
    root = logging.getLogger()
    original = root.level
    yield
    root.setLevel(original)


@pytest.fixture
def isolated_remote_home(tmp_path, monkeypatch):
    """A HOME with no ref config, archive, logs, or queue."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.delenv("REF_API_URL", raising=False)
    monkeypatch.setattr(cli, "CONFIG_DIR", str(home / ".config" / "ref"))
    monkeypatch.setattr(cli, "CONFIG_FILE", str(home / ".config" / "ref" / "config.yaml"))
    monkeypatch.setattr(cli, "log_directory", str(home / "references" / "logs"))
    monkeypatch.setattr(cli, "log_file_path", str(home / "references" / "logs" / "ref.log"))
    monkeypatch.setattr(
        cli, "error_log_file_path", str(home / "references" / "logs" / "ref_errors.log")
    )
    monkeypatch.setattr(cli, "UNIFIED", str(home / "references" / "references.md"))
    monkeypatch.setattr(
        cli,
        "TRANSCRIPT_PENDING_FILE",
        str(home / "references" / "transcripts" / "transcript-pending.md"),
    )
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", str(home / "references" / "transcripts"))
    monkeypatch.setattr(cli, "_file_logging_enabled", False)
    return home


def test_remote_ingest_creates_no_archive_config_logs_or_queue(
    isolated_remote_home, monkeypatch
):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://minion:8000")
    with patch("ref_cli.api_client.ingest_via_api", return_value=0) as ingest:
        with pytest.raises(SystemExit) as exc:
            cli.run_ingest("https://example.com/a", force=False)
    assert exc.value.code == 0
    ingest.assert_called_once_with("http://minion:8000", "https://example.com/a", force=False)

    home = isolated_remote_home
    assert not (home / "references").exists()
    assert not (home / ".config").exists()
    assert not (home / "references" / "logs").exists()


def test_routing_config_read_creates_nothing(isolated_remote_home):
    assert cli.read_config_for_routing() == {}
    assert cli.configured_api_base_url() is None
    assert not (isolated_remote_home / ".config").exists()


def test_remote_ingest_never_calls_google_metadata(isolated_remote_home, monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://minion:8000")
    with (
        patch("ref_cli.api_client.ingest_via_api", return_value=0),
        patch("ref_cli.cli.build", side_effect=AssertionError("Google call")),
        patch("ref_cli.cli.process_url", side_effect=AssertionError("local write")),
    ):
        with pytest.raises(SystemExit) as exc:
            cli.run_ingest("abcd1234567", force=False)
    assert exc.value.code == 0


def test_configured_api_receives_original_url_and_uses_http(
    isolated_remote_home, monkeypatch
):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://minion:8000")
    with (
        patch("ref_cli.api_client.ingest_urls", return_value=[]) as ingest_urls,
        patch("ref_cli.cli.process_url", side_effect=AssertionError("local write")),
        patch("ref_cli.cli.build", side_effect=AssertionError("Google call")),
    ):
        with pytest.raises(SystemExit) as exc:
            cli.run_ingest("https://example.com/path?x=1", force=True)
    assert exc.value.code == 0
    ingest_urls.assert_called_once_with(
        "http://minion:8000",
        url_value="https://example.com/path?x=1",
        force=True,
    )


def test_unreachable_api_exits_without_local_fallback(isolated_remote_home, monkeypatch):
    from ref_cli.api_client import ApiError

    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://minion:8000")
    with (
        patch("ref_cli.api_client.ingest_urls", side_effect=ApiError("unreachable")),
        patch("ref_cli.cli.process_url", side_effect=AssertionError("local write")),
    ):
        with pytest.raises(SystemExit) as exc:
            cli.run_ingest("https://example.com/a", force=False)
    assert exc.value.code == 1


def test_main_missing_api_exits_before_archive_bootstrap(
    isolated_remote_home, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "parse_arguments", lambda: _args(url="https://example.com"))
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with (
        patch("ref_cli.cli.ensure_path_exists") as ensure,
        patch("ref_cli.cli.ensure_references_migrated", create=True) as migrate,
        patch("ref_cli.cli.process_url") as process,
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 1
    ensure.assert_not_called()
    migrate.assert_not_called()
    process.assert_not_called()
    assert "ref: No API server configured." in capsys.readouterr().out
    assert not (isolated_remote_home / "references").exists()
    assert not (isolated_remote_home / ".config").exists()


def test_main_routes_url_before_local_logging_and_migration(
    isolated_remote_home, monkeypatch
):
    monkeypatch.setattr(cli, "parse_arguments", lambda: _args(url="https://example.com"))
    with (
        patch("ref_cli.cli.run_ingest") as run_ingest,
        patch("ref_cli.cli.ensure_path_exists") as ensure,
        patch("ref_cli.cli.enable_file_logging") as enable_logging,
        patch("ref_cli.cli.ensure_references_migrated", create=True) as migrate,
    ):
        cli.main()
    run_ingest.assert_called_once_with("https://example.com", force=False)
    ensure.assert_not_called()
    enable_logging.assert_not_called()
    migrate.assert_not_called()


def test_interactive_requires_api_before_prompt(isolated_remote_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    monkeypatch.setattr("sys.stdin", io.StringIO("https://example.com\n"))
    with patch("ref_cli.cli.process_url", side_effect=AssertionError("local write")):
        with pytest.raises(SystemExit) as exc:
            cli.run_interactive()
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "ref: No API server configured." in output
    assert "Enter a URL" not in output


def test_file_ingest_requires_api(isolated_remote_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with patch("ref_cli.cli.read_urls_from_file") as local:
        with pytest.raises(SystemExit) as exc:
            cli.run_file_ingest("/tmp/urls.txt", force=False)
    assert exc.value.code == 1
    local.assert_not_called()
    assert "ref: No API server configured." in capsys.readouterr().out


def test_file_ingest_configured_uses_api(monkeypatch):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://minion:8000")
    with patch("ref_cli.api_client.ingest_file_via_api") as remote:
        cli.run_file_ingest("/tmp/urls.txt", force=True)
    remote.assert_called_once_with("http://minion:8000", "/tmp/urls.txt", force=True)


def test_search_requires_api(isolated_remote_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with patch("ref_cli.cli.search_entries") as local_search:
        with pytest.raises(SystemExit) as exc:
            cli.run_search("example", field="title")
    assert exc.value.code == 1
    local_search.assert_not_called()
    assert "ref: No API server configured." in capsys.readouterr().out


def test_transcript_requires_api(isolated_remote_home, monkeypatch, capsys):
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with patch("ref_cli.cli.update_transcript") as local_update:
        with pytest.raises(SystemExit) as exc:
            cli.run_transcript("https://www.youtube.com/watch?v=abcd1234567")
    assert exc.value.code == 1
    local_update.assert_not_called()
    assert "ref: No API server configured." in capsys.readouterr().out


def test_missing_youtube_credentials_is_controlled(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "DEVELOPER_KEY", None)
    with patch("ref_cli.cli.build", side_effect=AssertionError("build called")):
        with pytest.raises(cli.YouTubeCredentialsError) as exc:
            cli.get_youtube_data("https://www.youtube.com/watch?v=abcd1234567")
    assert "YOUTUBE_API_KEY" in str(exc.value)
    assert "ref-api server" in str(exc.value)


def test_process_url_reports_missing_youtube_credentials_without_traceback(
    monkeypatch, capsys
):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "DEVELOPER_KEY", None)
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)
    with patch("ref_cli.cli.build", side_effect=AssertionError("build called")):
        cli.process_url("https://www.youtube.com/watch?v=abcd1234567", force=False)
    output = capsys.readouterr().out
    assert "Error: YouTube API credentials are not configured" in output
    assert "Traceback" not in output


def test_server_side_process_one_still_calls_process_url(monkeypatch):
    pytest.importorskip("fastapi")
    from ref_api import service

    calls = []

    def fake_process(url, force):
        calls.append((url, force))
        print("2026-11-09T00:00:00|[url]|(title)|uploader|YouTube|None")

    monkeypatch.setattr(
        service.ref_cli,
        "load_config",
        lambda: {"skip_patterns": []},
    )
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, cfg: False)
    monkeypatch.setattr(service.ref_cli, "is_youtube_video_id", lambda value: False)
    monkeypatch.setattr(service.ref_cli, "process_url", fake_process)

    result = service.process_one(
        "https://example.com/a", _discover_youtube_links=False
    )

    assert calls == [("https://example.com/a", False)]
    assert result.status in {"added", "exists"}
