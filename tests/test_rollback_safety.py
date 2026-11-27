"""Downgrade safety for Reddit discovery jobs.

An older ref-api reconstructs jobs without the additive ``source`` field
(``_normalize_job`` at base ``57abe0f``).  Pending/running Reddit discovery jobs
are consumed as no-op YouTube jobs, and *every* job -- including a terminal
failed one -- loses ``source`` on the older build's next snapshot write.  The
current build therefore blocks downgrade while any Reddit discovery job is
pending, running or failed.  A ``done`` job has no outstanding work and does not
block.
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
REDDIT_URL_2 = "https://www.reddit.com/r/example/comments/456/second"
REDDIT_URL_3 = "https://www.reddit.com/r/example/comments/789/third"
REDDIT_URL_4 = "https://www.reddit.com/r/example/comments/012/fourth"
VIDEO_URL = "https://www.youtube.com/watch?v=zmrPY6S1FwY"
HEADER = "# ref-references version=2\n"


class _LegacyQueueFormat:
    """The base ``57abe0f`` reader/writer, which has no ``source`` field.

    Copied faithfully enough to reproduce the downgrade hazard: ``load``
    normalizes jobs and drops unknown fields, and ``snapshot`` rewrites the whole
    table from the normalized records.
    """

    def __init__(self, jobs_path: str) -> None:
        self.jobs_path = jobs_path
        self.jobs: dict[str, dict] = {}

    @staticmethod
    def normalize(job_id: str, job: dict) -> dict:
        return {
            "id": job_id,
            "url": job["url"],
            "url_key": job.get("url_key") or job["url"],
            "parent_video_id": job.get("parent_video_id") or "",
            "kind": job.get("kind") or KIND_INGEST,
            "status": job.get("status", "pending"),
            "attempts": job.get("attempts", 0),
            "next_attempt_at": job.get("next_attempt_at", 0.0),
            "last_error": job.get("last_error") or "",
            "enqueued_at": job.get("enqueued_at", 0.0),
            "updated_at": job.get("updated_at", 0.0),
        }

    def load(self) -> None:
        with open(self.jobs_path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.jobs = {
            job_id: self.normalize(job_id, job)
            for job_id, job in data["jobs"].items()
        }

    def recover(self) -> int:
        recovered = 0
        for job in self.jobs.values():
            if job.get("status") == "running":
                job["status"] = "pending"
                recovered += 1
        if recovered:
            self.snapshot()
        return recovered

    def snapshot(self) -> None:
        # The old build rewrites the entire table from its normalized records.
        with open(self.jobs_path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": self.jobs}, handle, sort_keys=True)
            handle.write("\n")


@pytest.fixture
def env(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(archive))
    service._queue = None
    service._queue_dir = None
    return tmp_path


def _reddit_discover(queue: ShowNotesQueue, url: str = REDDIT_URL) -> str:
    return queue.enqueue_discovery(url, "", source=SOURCE_REDDIT)


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


def test_failed_reddit_discovery_blocks_downgrade(env):
    queue = service._get_queue()
    job_id = _reddit_discover(queue)
    queue.next_pending()
    queue.mark_failed(job_id, "permanent", retryable=False)

    result = service.rollback_safety()

    assert result["safe"] is False
    assert result["blocked"] is True
    assert result["corrupt"] is False
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["job_id"] == job_id
    assert result["blockers"][0]["status"] == "failed"
    assert result["failed_preserved"] == 1
    assert "source" in result["reason"]
    # Read-only: the failed job is still exactly where it was.
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


def test_legacy_queue_snapshot_strips_source_from_failed_jobs(env):
    """Compatibility regression for base ``57abe0f``'s reader/writer.

    The old ``_normalize_job`` has no ``source`` field.  It therefore strips the
    field from every record on its next snapshot write, including terminal
    failed jobs.  The guard must block downgrade before that can happen.
    """
    queue = service._get_queue()

    failed_id = _reddit_discover(queue, REDDIT_URL)
    assert queue.next_pending()["id"] == failed_id
    queue.mark_failed(failed_id, "permanent", retryable=False)

    running_id = _reddit_discover(queue, REDDIT_URL_2)
    assert queue.next_pending()["id"] == running_id

    done_id = _reddit_discover(queue, REDDIT_URL_3)
    assert queue.next_pending()["id"] == done_id
    queue.mark_done(done_id)

    pending_id = _reddit_discover(queue, REDDIT_URL_4)
    queue.enqueue_discovery(VIDEO_URL, "zmrPY6S1FwY")  # YouTube discovery
    queue.enqueue("https://example.org/child", kind=KIND_INGEST)

    result = service.rollback_safety()
    assert result["safe"] is False
    assert result["blocked"] is True
    blocking = {item["job_id"]: item["status"] for item in result["blockers"]}
    assert blocking == {
        failed_id: "failed",
        running_id: "running",
        pending_id: "pending",
    }
    assert done_id not in blocking
    assert result["failed_preserved"] == 1

    jobs_path = queue.jobs_path
    legacy = _LegacyQueueFormat(jobs_path)
    legacy.load()
    # The old reader drops the additive field during normalization.
    assert all("source" not in job for job in legacy.jobs.values())

    # A realistic old-build startup mutates a running job and rewrites the table.
    assert legacy.recover() == 1
    with open(jobs_path, encoding="utf-8") as handle:
        rewritten = json.load(handle)["jobs"]
    assert all("source" not in job for job in rewritten.values())
    assert rewritten[failed_id]["status"] == "failed"

    # Reloading with the current build shows the metadata is gone: the failed
    # Reddit job is now indistinguishable from a YouTube discovery job.
    reloaded = {job["id"]: job for job in ShowNotesQueue(str(env / "show_notes_queue")).jobs()}
    assert reloaded[failed_id]["status"] == "failed"
    assert reloaded[failed_id]["source"] == "youtube"


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
