"""Tests for GET /urls?domain=..., the client helper, and ``ref --url-dump``."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from ref_api.app import create_app
from ref_cli import api_client, cli

BASE_TS = "2026-01-01T00:00:00"


def _ts(hours: int) -> str:
    return (datetime.fromisoformat(BASE_TS) + timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def _row(ts: str, url: str, title: str = "Title") -> str:
    return f"{ts}|[{url}]|({title})|General|General"


@pytest.fixture
def client():
    """TestClient with archive bootstrap mocked (no real filesystem writes)."""
    with patch("ref_api.app._bootstrap_archive"):
        application = create_app()
        with TestClient(application) as test_client:
            yield test_client


# ---------------------------------------------------------------------------
# GET /urls route
# ---------------------------------------------------------------------------

EXPECTED_DUMP = [
    "https://docs.example.com/guide/a_b#c",
    "https://www.example.com/search?q=hello world&x=1#frag-üñîçødé",
    "https://WWW.Example.COM/Mixed-Case?q=1&x=2#frag",
    "https://example.com/oldest?keep=1",
]


@pytest.fixture
def archive(tmp_path):
    """Temporary references.md with deliberately out-of-order timestamps."""
    path = tmp_path / "references.md"
    lines = [
        "# ref-references version=2",
        _row(_ts(6), "https://docs.example.com/guide/a_b#c"),
        _row(_ts(1), "https://example.com/oldest?keep=1"),
        _row(_ts(2), "https://notexample.com/decoy"),
        _row(_ts(5), "https://www.example.com/search?q=hello world&x=1#frag-üñîçødé"),
        _row(_ts(4), "https://WWW.Example.COM/Mixed-Case?q=1&x=2#frag"),
        _row(_ts(3), "https://example.com.evil.net/decoy"),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_get_urls_dumps_domain_and_subdomains_newest_first(
    client: TestClient, archive, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "UNIFIED", str(archive))

    response = client.get("/urls", params={"domain": "example.com"})

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["urls"]
    # Exact stored strings, newest first, subdomains included, decoys excluded.
    assert body["urls"] == EXPECTED_DUMP


def test_get_urls_is_read_only(client: TestClient, archive, monkeypatch) -> None:
    monkeypatch.setattr(cli, "UNIFIED", str(archive))
    before = hashlib.sha256(archive.read_bytes()).hexdigest()

    client.get("/urls", params={"domain": "EXAMPLE.com"})

    assert hashlib.sha256(archive.read_bytes()).hexdigest() == before


def test_get_urls_empty_result_is_200_with_no_urls(
    client: TestClient, archive, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "UNIFIED", str(archive))

    response = client.get("/urls", params={"domain": "nothing-matches.example"})

    assert response.status_code == 200
    assert response.json() == {"urls": []}


def test_get_urls_rejects_blank_domain(client: TestClient) -> None:
    response = client.get("/urls", params={"domain": "   "})
    assert response.status_code == 400
    assert "non-empty" in response.json()["detail"]


@pytest.mark.parametrize(
    "raw",
    ["com", "https://example.com/path", "user@example.com", "bad-.com"],
)
def test_get_urls_rejects_malformed_domain(client: TestClient, raw: str) -> None:
    response = client.get("/urls", params={"domain": raw})
    assert response.status_code == 400
    assert "Invalid domain" in response.json()["detail"]


def test_get_urls_requires_domain_parameter(client: TestClient) -> None:
    response = client.get("/urls")
    # FastAPI validation (422) or our explicit 400 both reject the missing query.
    assert response.status_code in (400, 422)


def test_get_urls_missing_archive_returns_empty(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(cli, "UNIFIED", str(tmp_path / "absent.md"))

    response = client.get("/urls", params={"domain": "example.com"})

    assert response.status_code == 200
    assert response.json() == {"urls": []}


def test_get_urls_matches_scheme_less_urls_with_embedded_slashes(
    client: TestClient, tmp_path, monkeypatch
) -> None:
    """Stored scheme-less URLs with embedded ``//`` match by host; emails do not."""
    archive = tmp_path / "references.md"
    lines = [
        "# ref-references version=2",
        _row(_ts(4), "example.com/path?q=https://other.com"),
        _row(_ts(3), "example.com/foo//bar"),
        _row(_ts(2), "mailto:user@example.com"),
        _row(_ts(1), "user@example.com"),
    ]
    archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "UNIFIED", str(archive))

    response = client.get("/urls", params={"domain": "example.com"})

    assert response.status_code == 200
    assert response.json() == {
        "urls": ["example.com/path?q=https://other.com", "example.com/foo//bar"]
    }


def test_post_urls_and_get_list_behavior_unchanged(client: TestClient) -> None:
    """The new GET /urls route must not shadow POST /urls or GET /list."""
    with patch(
        "ref_api.service.process_many",
        return_value=[
            {
                "input": "https://example.com",
                "url": "https://example.com",
                "status": "added",
            }
        ],
    ) as mock_process:
        post = client.post("/urls", json={"url": "https://example.com"})
    assert post.status_code == 200
    mock_process.assert_called_once_with(["https://example.com"], force=False)

    with patch(
        "ref_api.service.list_archive", return_value=["https://example.com/x"]
    ) as mock_list:
        get = client.get("/list", params={"limit": 5})
    assert get.status_code == 200
    assert get.json() == {"urls": ["https://example.com/x"]}
    mock_list.assert_called_once_with(limit=5, since=None)


# ---------------------------------------------------------------------------
# api_client helpers
# ---------------------------------------------------------------------------

def test_urls_for_domain_calls_get_endpoint() -> None:
    with patch(
        "ref_cli.api_client._request_json",
        return_value={"urls": ["https://example.com/a"]},
    ) as mock_req:
        urls = api_client.urls_for_domain("http://minion:8000", "example.com")

    assert urls == ["https://example.com/a"]
    mock_req.assert_called_once_with(
        "GET",
        "http://minion:8000",
        "/urls",
        timeout=api_client.DEFAULT_SEARCH_TIMEOUT,
        params={"domain": "example.com"},
    )


def test_url_dump_via_api_prints_raw_urls_and_exits_zero(capsys) -> None:
    payload = {"urls": EXPECTED_DUMP}
    with patch("ref_cli.api_client._request_json", return_value=payload):
        code = api_client.url_dump_via_api("http://minion:8000", "example.com")

    captured = capsys.readouterr()
    assert code == 0
    # stdout is pure URLs: exact strings, one per line, no ANSI/color codes.
    assert captured.out.splitlines() == EXPECTED_DUMP
    assert "\x1b[" not in captured.out
    assert captured.err == ""


def test_url_dump_via_api_empty_result_is_clean_exit_zero(capsys) -> None:
    with patch("ref_cli.api_client._request_json", return_value={"urls": []}):
        code = api_client.url_dump_via_api("http://minion:8000", "example.com")

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_url_dump_via_api_reports_errors_on_stderr_only(capsys) -> None:
    with patch(
        "ref_cli.api_client._request_json",
        side_effect=api_client.ApiError(
            "ref API at minion:8000 returned 500 Internal Server Error for GET /urls."
        ),
    ):
        code = api_client.url_dump_via_api("http://minion:8000", "example.com")

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "500" in captured.err
    assert "minion:8000" in captured.err


# ---------------------------------------------------------------------------
# CLI routing (``ref --url-dump DOMAIN``)
# ---------------------------------------------------------------------------

def test_run_url_dump_uses_api_when_configured(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch(
        "ref_cli.api_client.url_dump_via_api", return_value=0
    ) as mock_dump:
        with pytest.raises(SystemExit) as exc:
            cli.run_url_dump("Example.COM")

    assert exc.value.code == 0
    # The domain is normalized before the request.
    mock_dump.assert_called_once_with("http://127.0.0.1:8000", "example.com")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_run_url_dump_requires_api_url(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: None)
    with patch("ref_cli.api_client.url_dump_via_api") as mock_dump:
        with pytest.raises(SystemExit) as exc:
            cli.run_url_dump("example.com")

    assert exc.value.code == 1
    mock_dump.assert_not_called()
    captured = capsys.readouterr()
    assert "ref: No API server configured." in captured.err
    assert "No URL processed." in captured.err
    # stdout stays pure even on failure.
    assert captured.out == ""


def test_run_url_dump_rejects_malformed_domain_before_http(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")
    with patch("ref_cli.api_client._request_json") as mock_req:
        with pytest.raises(SystemExit) as exc:
            cli.run_url_dump("https://example.com/path")

    assert exc.value.code == 1
    mock_req.assert_not_called()
    captured = capsys.readouterr()
    assert "Invalid domain" in captured.err
    assert captured.out == ""


def test_parse_arguments_exposes_url_dump_flag(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["ref", "--url-dump", "Example.COM"])
    args = cli.parse_arguments()
    assert args.url_dump == "Example.COM"


def test_main_dispatches_url_dump_without_archive_bootstrap(monkeypatch, capsys) -> None:
    """``--url-dump`` must run before any archive bootstrap/migration (read-only)."""
    args = type(
        "Args",
        (),
        {
            "status": False,
            "upgrade": False,
            "install_server": False,
            "uninstall_server": False,
            "server_status": False,
            "url_dump": "example.com",
            "verbose": False,
            "debug": None,
            "edit": False,
        },
    )()
    monkeypatch.setattr(cli, "parse_arguments", lambda: args)

    def _forbidden(*_args, **_kwargs):  # pragma: no cover - must never run
        raise AssertionError("archive bootstrap must not run for --url-dump")

    monkeypatch.setattr(cli, "ensure_path_exists", _forbidden)
    import ref_cli.references_format as references_format

    monkeypatch.setattr(references_format, "ensure_references_migrated", _forbidden)
    monkeypatch.setattr(cli, "configured_api_base_url", lambda: "http://127.0.0.1:8000")

    with patch(
        "ref_cli.api_client.url_dump_via_api", return_value=0
    ) as mock_dump:
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 0
    mock_dump.assert_called_once_with("http://127.0.0.1:8000", "example.com")
