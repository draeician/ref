"""Authoritative capture, exact lookup, idempotency and async discovery.

Deterministic tests use isolated archives. Provider/external-tool boundaries are
patched where noted; the HTTP integration test runs real FastAPI routes, a real
archive write, and a local fixture HTTP server.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from ref_api import service
from ref_api.app import create_app
from ref_api.show_notes_queue import (
    KIND_DISCOVER,
    KIND_INGEST,
    MAX_ATTEMPTS,
    SOURCE_REDDIT,
    SOURCE_YOUTUBE,
    QueueCorruptError,
    ShowNotesQueue,
)
from ref_cli import cli as ref_cli
from ref_cli.capture import capture_scope, current_capture, record_primary

HEADER = "# ref-references version=2\n"
REDDIT_SHORT = "https://redd.it/abc123"
REDDIT_CANONICAL = "https://www.reddit.com/r/example/comments/123/example"
VIDEO_URL = "https://www.youtube.com/watch?v=zmrPY6S1FwY"
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLabcdefghij"


@pytest.fixture
def archive(monkeypatch, tmp_path):
    """Isolated archive plus reset service-side queue/state caches."""
    path = tmp_path / "references.md"
    path.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(path))
    monkeypatch.setattr(service.ref_cli, "BASE", str(tmp_path))
    monkeypatch.setattr(
        service.ref_cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts")
    )
    monkeypatch.setattr(
        service.ref_cli,
        "TRANSCRIPT_PENDING_FILE",
        str(tmp_path / "transcripts" / "transcript-pending.md"),
    )
    monkeypatch.setattr(
        service.ref_cli, "OEMBED_CACHE_DIR", str(tmp_path / "transcripts" / "ombed")
    )
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: ref_cli.config)
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, cfg: False)
    for name in (
        "_queue",
        "_queue_dir",
        "_identity_store",
        "_identity_dir",
        "_idempotency_store",
        "_idempotency_dir",
    ):
        monkeypatch.setattr(service, name, None)
    return path


def _rows(path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def test_new_primary_capture_uses_stored_normalized_url(archive, monkeypatch):
    monkeypatch.setattr(
        ref_cli,
        "resolve_redirect",
        lambda url: "https://example.com/article?utm_source=share&id=1",
    )
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example title")

    result = service.process_one("https://example.com/in?utm_source=share&id=1")

    assert result.status == "added"
    assert result.primary is not None
    assert result.primary.status == "added"
    assert result.primary.archive_confirmed is True
    assert result.primary.canonical_url == "https://example.com/article?id=1"
    assert result.url == "https://example.com/article?id=1"
    assert result.input == "https://example.com/in?utm_source=share&id=1"
    assert _rows(archive)[0].endswith(
        "|[https://example.com/article?id=1]|(Example title)|General|General"
    )
    assert service.lookup_url("https://example.com/article?id=1").status == "exists"


def test_existing_general_capture_is_exists(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example")

    first = service.process_one("https://example.com/a")
    second = service.process_one("https://example.com/a")

    assert first.status == "added"
    assert second.status == "exists"
    assert second.primary is not None
    assert second.primary.canonical_url == "https://example.com/a"
    assert len(_rows(archive)) == 1


def test_existing_pdf_without_stdout_reports_exists(archive):
    url = "https://example.com/paper.pdf"
    archive.write_text(
        HEADER + f"2026-01-01T00:00:00|[{url}]|(paper.pdf)|PDF Document|General\n",
        encoding="utf-8",
    )

    result = service.process_one(url)

    assert result.status == "exists"
    assert result.output == ""
    assert result.primary is not None
    assert result.primary.status == "exists"
    assert result.primary.canonical_url == url
    assert result.primary.archive_confirmed is True
    assert len(_rows(archive)) == 1


def test_existing_playlist_without_stdout_reports_exists(archive, monkeypatch):
    archive.write_text(
        HEADER + f"2026-01-01T00:00:00|[{PLAYLIST_URL}]|(Playlist)|Channel|YouTube\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        ref_cli,
        "get_youtube_data",
        lambda url: ("Playlist", "Channel", []),
    )

    result = service.process_one(PLAYLIST_URL)

    assert result.status == "exists"
    assert result.output == ""
    assert result.primary is not None
    assert result.primary.status == "exists"
    assert result.primary.canonical_url == PLAYLIST_URL
    assert result.primary.archive_confirmed is True
    assert len(_rows(archive)) == 1


def test_reddit_short_link_records_authoritative_canonical(archive, monkeypatch):
    monkeypatch.setattr(
        ref_cli,
        "resolve_redirect",
        lambda url: REDDIT_CANONICAL + "/?utm_source=share",
    )
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")

    result = service.process_one(REDDIT_SHORT)

    assert result.status == "added"
    assert result.url == REDDIT_CANONICAL
    assert result.primary is not None
    assert result.primary.canonical_url == REDDIT_CANONICAL
    assert result.discovery is not None
    assert result.discovery.status == "queued"
    assert result.discovery.job_id
    assert _rows(archive)[0].endswith(
        f"|[{REDDIT_CANONICAL}]|(Example post)|General|General"
    )

    # The original short link reconciles to the stored canonical URL, including
    # after a process restart (drop in-memory store state).
    assert service.lookup_url(REDDIT_SHORT).status == "canonical"
    monkeypatch.setattr(service, "_identity_store", None)
    monkeypatch.setattr(service, "_identity_dir", None)
    after_restart = service.lookup_url(REDDIT_SHORT)
    assert after_restart.status == "canonical"
    assert after_restart.canonical_url == REDDIT_CANONICAL


def test_redirect_tracking_normalization_keeps_input_identity(archive, monkeypatch):
    monkeypatch.setattr(
        ref_cli,
        "resolve_redirect",
        lambda url: "https://example.com/final?b=2&utm_medium=x&a=1#frag",
    )
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Final")

    result = service.process_one("https://example.com/start")

    assert result.input == "https://example.com/start"
    assert result.url == "https://example.com/final?a=1&b=2"
    assert result.primary.canonical_url == "https://example.com/final?a=1&b=2"
    assert service.lookup_url("https://example.com/start").identity == "ledger"


def test_primary_success_is_not_overwritten_by_child_failure(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(ref_cli, "UNIFIED", str(archive))
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(
        ref_cli,
        "get_title_from_url",
        lambda url: "Parent" if "reddit.com" in url else (_ for _ in ()).throw(RuntimeError("child failed")),
    )
    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls",
        lambda url: ["https://example.com/child"],
    )

    with capture_scope():
        ref_cli.process_url(REDDIT_CANONICAL, force=False)

    capture, error = current_capture()
    assert capture is not None
    assert capture.status == "added"
    assert capture.url == REDDIT_CANONICAL
    assert error == ""


def test_primary_failure_is_not_overwritten_by_child_success(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(ref_cli, "UNIFIED", str(archive))
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)

    def title(url):
        if "reddit.com" in url:
            return "Dead link"
        return "Child title"

    monkeypatch.setattr(ref_cli, "get_title_from_url", title)
    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls",
        lambda url: ["https://example.com/child"],
    )

    with capture_scope():
        ref_cli.process_url(REDDIT_CANONICAL, force=False)

    capture, error = current_capture()
    assert capture is None
    assert error == "Dead link detected"
    assert len(_rows(archive)) == 1
    assert "example.com/child" in _rows(archive)[0]


def test_slow_reddit_discovery_does_not_delay_primary_http_response(
    archive, monkeypatch
):
    started = threading.Event()
    release = threading.Event()

    def slow_discovery(url):
        started.set()
        release.wait(timeout=15)
        from ref_cli.reddit import RedditDiscoveryResult

        return RedditDiscoveryResult(status="found", urls=[])

    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")
    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls_detailed", slow_discovery
    )

    try:
        with patch("ref_api.app._bootstrap_archive"):
            with TestClient(create_app()) as client:
                response = client.post("/urls", json={"url": REDDIT_CANONICAL})
                assert response.status_code == 200
                body = response.json()["results"][0]
                assert body["status"] == "added"
                assert body["primary"]["archive_confirmed"] is True
                assert body["discovery"]["status"] == "queued"
                # Discovery is on the worker and must not block the response.
                assert started.wait(timeout=5)
                assert not release.is_set()
    finally:
        release.set()
        service.stop_show_notes_worker()


def test_discovery_failure_is_independent_of_primary_capture(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")
    monkeypatch.setattr(service, "start_show_notes_worker", lambda: None)
    monkeypatch.setattr(service, "stop_show_notes_worker", lambda: None)

    result = service.process_one(REDDIT_CANONICAL)
    assert result.status == "added"
    assert result.discovery.status == "queued"

    from ref_cli.reddit import RedditDiscoveryResult

    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls_detailed",
        lambda url: RedditDiscoveryResult(status="unavailable", detail="HTTP 503"),
    )
    import ref_api.show_notes_queue as sq

    monkeypatch.setattr(sq, "RETRY_BASE_DELAY_SECONDS", 0.0)
    queue = service._get_queue()
    for _ in range(MAX_ATTEMPTS):
        assert service._drain_show_notes_queue(queue) is True

    assert queue.stats()["failed"] == 1
    assert result.primary.archive_confirmed is True
    job = next(job for job in queue.jobs() if job["kind"] == KIND_DISCOVER)
    assert job["source"] == SOURCE_REDDIT
    assert job["status"] == "failed"
    assert "503" in job["last_error"]


def test_queue_enqueue_failure_is_reported_as_failed_not_queued(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")
    monkeypatch.setattr(
        ShowNotesQueue,
        "enqueue_discovery",
        lambda self, *a, **k: (_ for _ in ()).throw(QueueCorruptError("bad jobs.json")),
    )

    result = service.process_one(REDDIT_CANONICAL)

    assert result.status == "added"
    assert result.primary.archive_confirmed is True
    assert result.discovery.status == "failed"
    assert "discovery not queued" in result.output
    assert "discovery queued" not in result.output


def test_exact_lookup_rejects_substring_and_unrelated_rows(archive):
    archive.write_text(
        HEADER
        + "2026-01-01T00:00:00|[https://example.com/path/child]|(Child)|General|General\n"
        + "2026-01-01T00:00:00|[https://unrelated.com/x]|(X)|General|General\n",
        encoding="utf-8",
    )

    assert service.lookup_url("https://example.com/path/child").status == "exists"
    assert service.lookup_url("https://example.com/path").status == "absent"
    assert service.lookup_url("https://example.com/path/chi").status == "absent"
    assert service.lookup_url("https://unrelated.com").status == "absent"


def test_ambiguous_timeout_reconciles_without_duplicate_capture(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example")
    url = "https://example.com/reconcile"
    key = "ambiguous-key-1"
    store = service._get_idempotency_store()
    store.begin(
        key,
        request_hash=service.request_hash([url], False),
        inputs=[url],
        force=False,
    )

    # Simulate the archive commit that happened before the response was lost.
    assert service.process_one(url).status == "added"

    results, replayed = service.process_many_idempotent([url], idempotency_key=key)
    assert replayed is False
    assert len(results) == 1
    assert results[0].status == "exists"
    assert results[0].primary.archive_confirmed is True
    assert len(_rows(archive)) == 1


def test_duplicate_and_concurrent_idempotent_submissions(
    archive, monkeypatch
):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example")
    key = "concurrent-key"
    url = REDDIT_CANONICAL

    def submit():
        return service.process_many_idempotent([url], idempotency_key=key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))

    assert len(_rows(archive)) == 1
    queue = service._get_queue()
    discovery_jobs = [job for job in queue.jobs() if job["kind"] == KIND_DISCOVER]
    assert len(discovery_jobs) == 1
    assert sorted(replayed for _results, replayed in outcomes) == [False, True]
    assert all(results[0].status in {"added", "exists"} for results, _ in outcomes)


def test_idempotency_key_with_different_payload_is_rejected(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example")

    with patch("ref_api.app._bootstrap_archive"):
        with TestClient(create_app()) as client:
            first = client.post(
                "/urls",
                json={"url": "https://example.com/a"},
                headers={"Idempotency-Key": "same-key"},
            )
            assert first.status_code == 200
            second = client.post(
                "/urls",
                json={"url": "https://example.com/b"},
                headers={"Idempotency-Key": "same-key"},
            )
            assert second.status_code == 409
            assert "different" in second.json()["detail"].lower()


def test_restart_recovery_after_capture_before_job_persistence(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")
    key = "interrupted-key"
    store = service._get_idempotency_store()
    store.begin(
        key,
        request_hash=service.request_hash([REDDIT_CANONICAL], False),
        inputs=[REDDIT_CANONICAL],
        force=False,
    )

    # Capture committed, but the process died before the discovery job existed.
    captured = service.process_one(REDDIT_CANONICAL, _discover_reddit_links=False)
    assert captured.status == "added"
    assert captured.discovery is None
    assert service._get_queue().jobs() == []

    results, replayed = service.process_many_idempotent(
        [REDDIT_CANONICAL], idempotency_key=key
    )
    assert replayed is False
    assert results[0].status == "exists"
    assert results[0].discovery.status == "queued"
    assert len(_rows(archive)) == 1
    discovery_jobs = [
        job
        for job in service._get_queue().jobs()
        if job["kind"] == KIND_DISCOVER
    ]
    assert len(discovery_jobs) == 1


def test_discovery_is_queued_when_url_was_already_ingested_as_child(archive, monkeypatch):
    """A done ingest job must not suppress a later discovery job for the URL."""
    queue = service._get_queue()
    ingest_job = queue.enqueue(REDDIT_CANONICAL, kind=KIND_INGEST)
    queue.mark_done(ingest_job)
    archive.write_text(
        HEADER
        + f"2026-01-01T00:00:00|[{REDDIT_CANONICAL}]|(Example post)|General|General\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(ref_cli, "get_title_from_url", lambda url: "Example post")

    result = service.process_one(REDDIT_CANONICAL)

    assert result.status == "exists"
    assert result.discovery is not None
    assert result.discovery.status == "queued"
    assert queue.find_job(REDDIT_CANONICAL, kind=KIND_INGEST)["id"] == ingest_job
    assert queue.find_job(REDDIT_CANONICAL, kind=KIND_DISCOVER) is not None


def test_existing_queue_snapshot_loads_without_source_field(archive, tmp_path):
    queue_dir = tmp_path / "legacy_queue"
    queue_dir.mkdir()
    jobs = {
        "jobs": {
            "legacy1": {
                "id": "legacy1",
                "url": VIDEO_URL,
                "url_key": VIDEO_URL,
                "parent_video_id": "zmrPY6S1FwY",
                "kind": "discover",
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": 1.0,
                "last_error": "",
                "enqueued_at": 1.0,
                "updated_at": 1.0,
            }
        }
    }
    (queue_dir / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")

    queue = ShowNotesQueue(str(queue_dir))
    loaded = queue.jobs()
    assert len(loaded) == 1
    assert loaded[0]["source"] == SOURCE_YOUTUBE
    assert queue.stats()["pending"] == 1


def test_discovered_reddit_playlist_is_link_only(archive, monkeypatch):
    calls = []

    def record_link(url, force):
        calls.append(("record_link", url))
        record_primary("added", url)

    monkeypatch.setattr(service.ref_cli, "record_youtube_playlist_link", record_link)
    monkeypatch.setattr(
        service.ref_cli,
        "process_url",
        lambda url, force, **kwargs: calls.append(("process_url", url)),
    )
    monkeypatch.setattr(service, "_exact_archive_match", lambda url: True)

    result = service.process_one(
        PLAYLIST_URL,
        _discover_youtube_links=False,
        _discover_reddit_links=False,
        _suppress_playlist_expansion=True,
    )

    assert result.status == "added"
    assert calls == [("record_link", PLAYLIST_URL)]


def test_existing_youtube_parent_queues_youtube_discovery(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(
        ref_cli,
        "get_youtube_data",
        lambda url: ("zmrPY6S1FwY", "Title", "Channel", "2026-01-01"),
    )
    monkeypatch.setattr(
        ref_cli, "fetch_youtube_transcript", lambda *a, **k: (None, None)
    )
    monkeypatch.setattr(
        ref_cli, "resolve_transcript_failure_placeholder", lambda *a, **k: "None"
    )
    monkeypatch.setattr(ref_cli, "reference_has_transcript", lambda url: False)
    monkeypatch.setattr(ref_cli, "update_reference_entry", lambda *a, **k: record_primary("added", a[0]))
    monkeypatch.setattr(service, "_exact_archive_match", lambda url: True)

    result = service.process_one(VIDEO_URL)

    assert result.status == "added"
    assert result.discovery is not None
    assert result.discovery.status == "queued"
    job = service._get_queue().find_job(VIDEO_URL, kind=KIND_DISCOVER)
    assert job["source"] == SOURCE_YOUTUBE


def test_generic_error_preserves_sanitized_reason(archive, monkeypatch):
    monkeypatch.setattr(ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(
        ref_cli,
        "get_title_from_url",
        lambda url: "Error: Unexpected error - token=super-secret boom",
    )

    result = service.process_one("https://example.com/broken")

    assert result.status == "error"
    assert "Unexpected error" in result.error
    assert "super-secret" not in result.error
    assert "token=***" in result.error
    assert "Reason:" in result.output


def test_exact_lookup_reports_archive_failure(archive, monkeypatch):
    archive.unlink()
    result = service.lookup_url("https://example.com/a")
    assert result.status == "error"
    assert "not found" in (result.error or "")


def test_exact_lookup_reports_invalid_identity(archive):
    result = service.lookup_url("not-a-url")
    assert result.status == "unknown"
    assert result.identity == "invalid"


def test_ref_cli_renders_legacy_and_structured_results(capsys):
    from ref_cli.api_client import print_ingest_results

    code = print_ingest_results(
        [
            {
                "input": "https://example.com/a.pdf",
                "url": "https://example.com/a.pdf",
                "status": "exists",
                "message": "Already recorded",
                "output": "",
            },
            {
                "input": "https://example.com/error",
                "url": "https://example.com/error",
                "status": "error",
                "message": "boom",
                "output": "",
                "error": "boom",
            },
        ]
    )
    output = capsys.readouterr().out
    assert code == 1
    assert "boom" in output
    assert "Already recorded" not in output  # exists with no stdout stays quiet


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler name
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header(
                "Location", "/article?utm_source=share&id=1"
            )
            self.end_headers()
            return
        body = (
            "<html><head><title>Fixture article</title></head>"
            "<body>ok</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


@pytest.fixture
def fixture_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_integration_real_routes_archive_and_contract(
    fixture_server, archive, monkeypatch
):
    """Real FastAPI routes + real archive write + fixture HTTP server.

    External-tool boundary: lynx is replaced by a fixture HTTP fetch/parse so the
    test is deterministic on hosts without lynx. Redirect resolution, archive
    parsing/writing, routes, lookup, identity state and idempotency are real.
    """

    def fixture_title(url: str) -> str:
        import requests

        response = requests.get(url, timeout=5)
        response.raise_for_status()
        start = response.text.find("<title>")
        end = response.text.find("</title>")
        return response.text[start + 7:end] if start >= 0 and end >= 0 else "No title found"

    monkeypatch.setattr(ref_cli, "get_title_from_url", fixture_title)
    original = f"{fixture_server}/redirect?utm_source=x"
    canonical = f"{fixture_server}/article?id=1"

    with TestClient(create_app()) as client:
        response = client.post("/urls", json={"url": original})
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["input"] == original
        assert result["url"] == canonical
        assert result["status"] == "added"
        assert result["primary"] == {
            "status": "added",
            "canonical_url": canonical,
            "archive_confirmed": True,
            "source": "General",
            "identity_recorded": True,
        }
        assert result["discovery"] is None

        assert _rows(archive)[0].endswith(
            f"|[{canonical}]|(Fixture article)|General|General"
        )

        exact = client.get("/urls/exists", params={"url": canonical}).json()
        assert exact["status"] == "exists"
        assert exact["exact_match"] is True

        canonical_lookup = client.get(
            "/urls/exists", params={"url": original}
        ).json()
        assert canonical_lookup["status"] == "canonical"
        assert canonical_lookup["canonical_url"] == canonical
        assert canonical_lookup["archive_confirmed"] is True

        first = client.post(
            "/urls",
            json={"url": original},
            headers={"Idempotency-Key": "integration-key"},
        )
        second = client.post(
            "/urls",
            json={"url": original},
            headers={"Idempotency-Key": "integration-key"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.headers.get("Idempotent-Replayed") == "true"

        status = client.get("/requests/integration-key").json()
        assert status["state"] == "completed"
        assert status["inputs"] == [original]

        capabilities = client.get("/capabilities").json()
        assert capabilities["api_contract_version"] == "2"
        assert capabilities["features"]["structured_primary"] is True
        assert capabilities["features"]["async_reddit_discovery"] is True
