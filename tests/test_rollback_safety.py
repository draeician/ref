"""Downgrade safety for outstanding Reddit discovery jobs.

An older ref-api would consume a Reddit ``discover`` job as a no-op YouTube job
and mark it done.  The current build therefore exposes a read-only check that
blocks downgrade while such jobs are pending/running, preserving failed jobs
without treating them as incompatible.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ref_api import service
from ref_api.app import create_app
from ref_api.show_notes_queue import (
    KIND_DISCOVER,
    KIND_INGEST,
    SOURCE_REDDIT,
    ShowNotesQueue,
)

REDDIT_URL = "https://www.reddit.com/r/example/comments/123/example"
VIDEO_URL = "https://www.youtube.com/watch?v=zmrPY6S1FwY"
HEADER = "# ref-references version=2\n"


@pytest.fixture
def env(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(archive))
    service._queue = None
    service._queue_dir = None
    return tmp_path


def _reddit_discover(queue: ShowNotesQueue) -> str:
    return queue.enqueue_discovery(REDDIT_URL, "", source=SOURCE_REDDIT)


@pytest.mark.parametrize("status", ["pending", "running"])
def test_pending_or_running_reddit_discovery_blocks_downgrade(env, status):
    queue = service._get_queue()
    job_id = _reddit_discover(queue)
    if status == "running":
        claimed = queue.next_pending()
        assert claimed["id"] == job_id
        assert claimed["status"] == "running"
    else:
        assert {j["id"]: j for j in queue.jobs()}[job_id]["status"] == "pending"

    result = service.rollback_safety()

    assert result["safe"] is False
    assert result["blocked"] is True
    assert result["corrupt"] is False
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["job_id"] == job_id
    assert result["blockers"][0]["status"] == status
    assert "Downgrade blocked" in result["reason"]
    # Read-only: the job is still exactly where it was.
    assert {j["id"]: j for j in queue.jobs()}[job_id]["status"] == status


def test_failed_reddit_discovery_is_preserved_and_does_not_block(env):
    queue = service._get_queue()
    job_id = _reddit_discover(queue)
    queue.next_pending()
    queue.mark_failed(job_id, "permanent", retryable=False)

    result = service.rollback_safety()

    assert result["safe"] is True
    assert result["blocked"] is False
    assert result["blockers"] == []
    assert result["failed_preserved"] == 1
    assert {j["id"]: j for j in queue.jobs()}[job_id]["status"] == "failed"


def test_completed_reddit_discovery_does_not_block(env):
    queue = service._get_queue()
    job_id = _reddit_discover(queue)
    queue.next_pending()
    queue.mark_done(job_id)

    result = service.rollback_safety()

    assert result["safe"] is True
    assert result["blockers"] == []
    assert result["failed_preserved"] == 0


def test_other_job_kinds_and_sources_do_not_block(env):
    queue = service._get_queue()
    queue.enqueue_discovery(VIDEO_URL, "zmrPY6S1FwY")  # YouTube default
    queue.enqueue(REDDIT_URL, kind=KIND_INGEST, source=SOURCE_REDDIT)
    queue.enqueue("https://example.org/a", kind=KIND_INGEST)

    result = service.rollback_safety()

    assert result["safe"] is True
    assert result["blocked"] is False
    assert result["blockers"] == []


def test_corrupt_queue_blocks_downgrade(env):
    queue_dir = env / "show_notes_queue"
    queue_dir.mkdir()
    (queue_dir / "jobs.json").write_text("{ not valid json", encoding="utf-8")
    service._queue = ShowNotesQueue(str(queue_dir))
    service._queue_dir = str(queue_dir)

    result = service.rollback_safety()

    assert result["safe"] is False
    assert result["blocked"] is True
    assert result["corrupt"] is True
    assert result["blockers"] == []
    assert "corrupt" in result["reason"]


def test_rollback_check_command_exit_codes(monkeypatch, capsys):
    from ref_api import server

    args = server.parse_args(["--rollback-check"])
    assert args.rollback_check is True

    monkeypatch.setattr(
        service,
        "rollback_safety",
        lambda: {"safe": True, "blocked": False, "reason": "ok"},
    )
    assert server.run_rollback_check() == 0
    assert json.loads(capsys.readouterr().out)["safe"] is True

    monkeypatch.setattr(
        service,
        "rollback_safety",
        lambda: {"safe": False, "blocked": True, "reason": "blocked"},
    )
    assert server.run_rollback_check() == 2
    assert json.loads(capsys.readouterr().out)["blocked"] is True


def test_rollback_safety_route_is_read_only(env, monkeypatch):
    queue = service._get_queue()
    job_id = _reddit_discover(queue)
    before = {j["id"]: j for j in queue.jobs()}

    monkeypatch.setattr(service, "start_show_notes_worker", lambda: None)
    monkeypatch.setattr(service, "stop_show_notes_worker", lambda: None)
    monkeypatch.setattr(service, "start_transcript_reconciler", lambda **kw: False)
    monkeypatch.setattr(service, "stop_transcript_reconciler", lambda **kw: None)

    with patch("ref_api.app._bootstrap_archive"):
        from fastapi.testclient import TestClient

        with TestClient(create_app()) as client:
            response = client.get("/queue/rollback-safety")

    assert response.status_code == 200
    body = response.json()
    assert body["safe"] is False
    assert body["blocked"] is True
    assert body["blockers"][0]["job_id"] == job_id
    assert {j["id"]: j for j in queue.jobs()} == before


def test_rollback_safety_is_advertised_in_capabilities(env, monkeypatch):
    monkeypatch.setattr(service, "start_show_notes_worker", lambda: None)
    monkeypatch.setattr(service, "stop_show_notes_worker", lambda: None)
    monkeypatch.setattr(service, "start_transcript_reconciler", lambda **kw: False)
    monkeypatch.setattr(service, "stop_transcript_reconciler", lambda **kw: None)

    with patch("ref_api.app._bootstrap_archive"):
        from fastapi.testclient import TestClient

        with TestClient(create_app()) as client:
            body = client.get("/capabilities").json()

    assert body["features"]["rollback_safety_check"] is True
    assert body["features"]["idempotency_ambiguous_state"] is True
