"""Offline FastAPI TestClient tests for ref-api (mocked ingest)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.responses import FileResponse
from fastapi.testclient import TestClient

from ref_api.app import create_app


SPECIAL_URL = "https://example.com/search?q=hello world&x=1#frag-üñîçødé"


@pytest.fixture
def client():
    """TestClient with archive bootstrap mocked (no real filesystem writes)."""
    with patch("ref_api.app._bootstrap_archive"):
        application = create_app()
        with TestClient(application) as test_client:
            yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_post_urls_single_preserves_special_characters(client: TestClient) -> None:
    """JSON body must deliver ?, &, #, spaces, and unicode intact to process_url."""
    with (
        patch("ref_api.service.ref_cli.load_config", return_value={}),
        patch("ref_api.service.ref_cli.should_skip_url", return_value=False),
        patch("ref_api.service.ref_cli.is_youtube_video_id", return_value=False),
        patch("ref_api.service.ref_cli.process_url") as mock_process,
    ):

        def _fake_process(url: str, force: bool) -> None:
            print(f"recorded|{url}")

        mock_process.side_effect = _fake_process

        response = client.post(
            "/urls",
            json={"url": SPECIAL_URL, "force": False},
        )

    assert response.status_code == 200
    mock_process.assert_called_once_with(SPECIAL_URL, False)
    result = response.json()["results"][0]
    assert result["input"] == SPECIAL_URL
    assert result["url"] == SPECIAL_URL
    assert result["status"] == "added"


def test_post_urls_list_payload(client: TestClient) -> None:
    urls = [
        "https://example.com/a?x=1&y=2",
        "https://example.com/b#section",
    ]
    with (
        patch("ref_api.service.ref_cli.load_config", return_value={}),
        patch("ref_api.service.ref_cli.should_skip_url", return_value=False),
        patch("ref_api.service.ref_cli.is_youtube_video_id", return_value=False),
        patch("ref_api.service.ref_cli.process_url") as mock_process,
    ):

        def _fake_process(url: str, force: bool) -> None:
            print(f"recorded|{url}")

        mock_process.side_effect = _fake_process

        response = client.post("/urls", json={"urls": urls, "force": True})

    assert response.status_code == 200
    assert mock_process.call_count == 2
    mock_process.assert_any_call(urls[0], True)
    mock_process.assert_any_call(urls[1], True)
    results = response.json()["results"]
    assert len(results) == 2
    assert [r["input"] for r in results] == urls
    assert all(r["status"] == "added" for r in results)


def test_skip_pattern_short_circuit(client: TestClient) -> None:
    skipped = "https://mail.google.com/mail/u/0/#inbox"
    with (
        patch("ref_api.service.ref_cli.load_config", return_value={"skip_patterns": ["*"]}),
        patch("ref_api.service.ref_cli.should_skip_url", return_value=True) as mock_skip,
        patch("ref_api.service.ref_cli.process_url") as mock_process,
    ):
        response = client.post("/urls", json={"url": skipped})

    assert response.status_code == 200
    mock_skip.assert_called()
    mock_process.assert_not_called()
    result = response.json()["results"][0]
    assert result["input"] == skipped
    assert result["url"] == skipped
    assert result["status"] == "skipped"
    assert "skip" in result["message"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": ""},
        {"url": "   "},
        {"urls": []},
        {"urls": ["", "  "]},
        {"force": False},
    ],
)
def test_empty_or_invalid_body_returns_client_error(
    client: TestClient, payload: dict
) -> None:
    response = client.post("/urls", json=payload)
    # Route raises 400; Pydantic request validation may surface as 422.
    assert response.status_code in (400, 422)


def test_invalid_json_body_returns_client_error(client: TestClient) -> None:
    response = client.post(
        "/urls",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)


def test_search_all_fields(client: TestClient) -> None:
    line = "2026-01-01T00:00:00|[https://example.com]|(Example)|General|General\n"
    with patch(
        "ref_api.service.ref_cli.search_entries",
        side_effect=lambda term, field, path: (
            {line: ["Url"]} if field == "url" else {}
        ),
    ):
        response = client.get("/search", params={"q": "example", "field": "all"})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["line"] == line
    assert body["results"][0]["hit_types"] == ["Url"]


def test_search_by_title(client: TestClient) -> None:
    line = "2026-01-01T00:00:00|[https://example.com]|(Example Title)|General|General\n"
    with patch(
        "ref_api.service.ref_cli.search_entries",
        return_value={line: ["Title"]},
    ) as mock_search:
        response = client.get(
            "/search",
            params={"q": "Example Title", "field": "title"},
        )

    assert response.status_code == 200
    mock_search.assert_called_once()
    assert mock_search.call_args[0][1] == "title"
    assert response.json()["results"][0]["hit_types"] == ["Title"]


def test_search_empty_query_returns_400(client: TestClient) -> None:
    response = client.get("/search", params={"q": "   "})
    assert response.status_code == 400


def test_backup_download(client: TestClient, tmp_path) -> None:
    backup_file = tmp_path / "20260101T120000_references.md.gz"
    backup_file.write_bytes(b"gzipped-content")
    with (
        patch("ref_api.service.create_references_backup", return_value=str(backup_file)),
        patch("ref_api.routes.FileResponse", side_effect=lambda path, **kw: FileResponse(path, **kw)),
    ):
        response = client.post("/backup", params={"compress": "true"})

    assert response.status_code == 200
    assert response.content == b"gzipped-content"
    assert "references.md.gz" in response.headers.get("content-disposition", "")


def test_transcript_update(client: TestClient) -> None:
    with patch(
        "ref_api.service.update_transcript_for_url",
        return_value=__import__(
            "ref_api.schemas", fromlist=["TranscriptResult"]
        ).TranscriptResult(
            url="https://www.youtube.com/watch?v=abcd1234567",
            status="updated",
            message="Transcript updated",
            output="Transcript for https://www.youtube.com/watch?v=abcd1234567 has been updated.",
        ),
    ):
        response = client.post(
            "/transcript",
            json={"url": "https://www.youtube.com/watch?v=abcd1234567"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"] == "updated"


def test_transcript_empty_url_returns_400(client: TestClient) -> None:
    response = client.post("/transcript", json={"url": "   "})
    assert response.status_code == 400
