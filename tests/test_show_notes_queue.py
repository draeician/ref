"""Unit tests for the durable show-note work queue."""

from __future__ import annotations

import json
import os

import pytest

from ref_api.show_notes_queue import (
    KIND_DISCOVER,
    MAX_ATTEMPTS,
    QueueCorruptError,
    ShowNotesQueue,
)


def _new_queue(tmp_path):
    return ShowNotesQueue(str(tmp_path / "show_notes_queue"))


def test_enqueue_creates_persistent_pending_job(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a", parent_video_id="vid1")
    assert job_id
    jobs = queue.jobs()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "pending"
    assert jobs[0]["url"] == "https://example.org/a"
    assert jobs[0]["parent_video_id"] == "vid1"
    assert jobs[0]["kind"] == "ingest"
    assert os.path.exists(queue.jobs_path)


def test_enqueue_dedupes_unfinished_duplicate(tmp_path):
    queue = _new_queue(tmp_path)
    first = queue.enqueue("https://example.org/a")
    second = queue.enqueue("https://example.org/a")
    assert first is not None
    assert second is None
    assert len(queue.jobs()) == 1


def test_enqueue_skips_completed_work(tmp_path):
    """A URL whose job already completed must not be re-enqueued by default."""
    queue = _new_queue(tmp_path)
    first = queue.enqueue("https://example.org/a")
    queue.mark_done(first)
    assert queue.enqueue("https://example.org/a") is None
    assert len(queue.jobs()) == 1


def test_failed_job_can_be_reenqueued(tmp_path):
    """A failed job is an intentional retry: re-submission may enqueue again."""
    queue = _new_queue(tmp_path)
    first = queue.enqueue("https://example.org/a")
    queue.next_pending()
    queue.mark_failed(first, "boom", retryable=False)
    second = queue.enqueue("https://example.org/a")
    assert second is not None
    assert second != first


def test_recover_requeues_running_jobs(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a")
    claimed = queue.next_pending()
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"

    # Simulate a restart: a fresh queue object over the same directory.
    restarted = _new_queue(tmp_path)
    recovered = restarted.recover()
    assert recovered == 1
    jobs = {j["id"]: j for j in restarted.jobs()}
    assert jobs[job_id]["status"] == "pending"


def test_next_pending_respects_backoff_deadline(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a")
    # Force a future retry deadline by failing then inspecting.
    queue.next_pending()
    queue.mark_failed(job_id, "boom", retryable=True)
    assert queue.next_pending() is None  # still within backoff window


def test_bounded_retries_then_terminal_failure(tmp_path, monkeypatch):
    import ref_api.show_notes_queue as sq

    monkeypatch.setattr(sq, "RETRY_BASE_DELAY_SECONDS", 0.0)
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a")
    for _ in range(MAX_ATTEMPTS - 1):
        claimed = queue.next_pending()
        assert claimed is not None
        queue.mark_failed(job_id, "boom", retryable=True)
    # The final attempt exceeds the bound and becomes terminal.
    claimed = queue.next_pending()
    assert claimed is not None
    queue.mark_failed(job_id, "boom", retryable=True)
    jobs = {j["id"]: j for j in queue.jobs()}
    assert jobs[job_id]["status"] == "failed"
    assert jobs[job_id]["attempts"] == MAX_ATTEMPTS


def test_mark_failed_retryable_keeps_pending_until_bound(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a")
    queue.next_pending()
    queue.mark_failed(job_id, "transient", retryable=True)
    jobs = {j["id"]: j for j in queue.jobs()}
    assert jobs[job_id]["status"] == "pending"
    assert jobs[job_id]["next_attempt_at"] > 0
    assert jobs[job_id]["last_error"] == "transient"


def test_mark_failed_nonretryable_is_terminal(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a")
    queue.next_pending()
    queue.mark_failed(job_id, "permanent", retryable=False)
    jobs = {j["id"]: j for j in queue.jobs()}
    assert jobs[job_id]["status"] == "failed"


def test_stats_and_unfinished(tmp_path):
    queue = _new_queue(tmp_path)
    queue.enqueue("https://example.org/a")
    queue.enqueue("https://example.org/b")
    queue.next_pending()
    assert queue.stats()["pending"] == 1
    assert queue.stats()["running"] == 1
    assert queue.stats()["corrupt"] == 0
    assert queue.unfinished_count() == 2


def test_enqueue_many_batches_and_dedupes(tmp_path):
    queue = _new_queue(tmp_path)
    queued, skipped = queue.enqueue_many(
        ["https://example.org/a", "https://example.org/b"], parent_video_id="vid1"
    )
    assert queued == 2
    assert skipped == 0
    assert len(queue.jobs()) == 2

    queued2, skipped2 = queue.enqueue_many(
        ["https://example.org/a", "https://example.org/c"]
    )
    assert queued2 == 1
    assert skipped2 == 1


def test_discover_job_kind_round_trips(tmp_path):
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue_discovery("https://www.youtube.com/watch?v=x", "x")
    job = {j["id"]: j for j in queue.jobs()}[job_id]
    assert job["kind"] == KIND_DISCOVER
    assert job["parent_video_id"] == "x"


def test_terminal_history_is_bounded(tmp_path, monkeypatch):
    import ref_api.show_notes_queue as sq

    monkeypatch.setattr(sq, "MAX_TERMINAL_JOBS", 3)
    queue = _new_queue(tmp_path)
    ids = []
    for i in range(6):
        job_id = queue.enqueue(f"https://example.org/{i}")
        queue.mark_done(job_id)
        ids.append(job_id)
    terminal_ids = {j["id"] for j in queue.jobs() if j["status"] == "done"}
    assert len(terminal_ids) <= 3
    assert ids[-1] in terminal_ids
    assert ids[0] not in terminal_ids


def test_corrupt_jobs_file_fails_closed(tmp_path):
    queue = _new_queue(tmp_path)
    os.makedirs(queue.queue_dir, exist_ok=True)
    original = "{ not valid json"
    with open(queue.jobs_path, "w", encoding="utf-8") as handle:
        handle.write(original)

    assert queue.is_corrupt() is True
    assert queue.stats()["corrupt"] == 1
    assert "malformed" in queue.corrupt_error()

    # Fail closed: no mutation is allowed, so accepted work is never overwritten.
    with pytest.raises(QueueCorruptError):
        queue.enqueue("https://example.org/a")
    with pytest.raises(QueueCorruptError):
        queue.recover()

    # Original bytes preserved untouched.
    with open(queue.jobs_path, encoding="utf-8") as handle:
        assert handle.read() == original


def test_schema_invalid_job_fails_closed(tmp_path):
    queue = _new_queue(tmp_path)
    os.makedirs(queue.queue_dir, exist_ok=True)
    with open(queue.jobs_path, "w", encoding="utf-8") as handle:
        json.dump(
            {"jobs": {"j1": {"id": "j1", "url": "https://example.org/a", "status": "bogus"}}},
            handle,
        )
    assert queue.is_corrupt() is True
    with pytest.raises(QueueCorruptError):
        queue.enqueue("https://example.org/a")


# ---------------------------------------------------------------------------
# Fail-before regressions: a malformed existing jobs.json must fail closed and
# must never be overwritten by a later enqueue, for every field the worker
# persists. Each fixture writes a deliberately invalid queue, confirms the queue
# is corrupt, attempts an enqueue (which must raise, not overwrite), and asserts
# the original bytes are byte-for-byte intact.
# ---------------------------------------------------------------------------


def _write_raw_jobs(tmp_path, raw: bytes) -> ShowNotesQueue:
    queue = _new_queue(tmp_path)
    os.makedirs(queue.queue_dir, exist_ok=True)
    with open(queue.jobs_path, "wb") as handle:
        handle.write(raw)
    return queue


def _assert_fail_closed_preserves_bytes(queue, original: bytes) -> None:
    assert queue.is_corrupt() is True
    assert queue.stats()["corrupt"] == 1
    with pytest.raises(QueueCorruptError):
        queue.enqueue("https://example.org/new")
    with pytest.raises(QueueCorruptError):
        queue.recover()
    with open(queue.jobs_path, "rb") as handle:
        assert handle.read() == original


@pytest.mark.parametrize(
    "bad_jobs",
    [
        # attempts is not an integer (the architect's canonical example).
        {"j1": {"id": "j1", "url": "https://example.org/a", "status": "pending", "attempts": "bad"}},
        # status is unhashable -> old code raised TypeError mid-validation.
        {"j1": {"id": "j1", "url": "https://example.org/a", "status": ["pending"]}},
        # inner id does not match the authoritative outer key.
        {"j1": {"id": "j2", "url": "https://example.org/a", "status": "pending"}},
        # unknown job kind.
        {"j1": {"id": "j1", "url": "https://example.org/a", "status": "pending", "kind": "weird"}},
        # non-numeric timestamp.
        {"j1": {"id": "j1", "url": "https://example.org/a", "status": "pending", "enqueued_at": "soon"}},
        # url is not a string.
        {"j1": {"id": "j1", "url": 123, "status": "pending"}},
        # job entry is not an object.
        {"j1": "not-an-object"},
    ],
)
def test_malformed_job_field_fails_closed_and_preserves_bytes(tmp_path, bad_jobs):
    payload = json.dumps({"jobs": bad_jobs}, sort_keys=True).encode("utf-8")
    queue = _write_raw_jobs(tmp_path, payload)
    _assert_fail_closed_preserves_bytes(queue, payload)


def test_undecodable_queue_fails_closed_and_preserves_bytes(tmp_path):
    raw = b'{"jobs": {"j1": {"id": "j1", "url": "https://example.org/a", "status": "pending"}}}\xff\xfe'
    queue = _write_raw_jobs(tmp_path, raw)
    _assert_fail_closed_preserves_bytes(queue, raw)


def test_valid_queue_reloads_and_normalizes_id(tmp_path):
    """A well-formed queue survives strict validation and keeps id==outer key."""
    queue = _new_queue(tmp_path)
    job_id = queue.enqueue("https://example.org/a", parent_video_id="vid1")
    queue.next_pending()  # -> running

    restarted = _new_queue(tmp_path)
    restarted.recover()
    jobs = {j["id"]: j for j in restarted.jobs()}
    assert jobs[job_id]["id"] == job_id
    assert jobs[job_id]["status"] == "pending"
    assert jobs[job_id]["attempts"] == 1
    # State transitions still resolve by id after a strict reload.
    restarted.mark_done(job_id)
    assert {j["id"]: j for j in restarted.jobs()}[job_id]["status"] == "done"


def test_enqueue_rejects_empty_url(tmp_path):
    queue = _new_queue(tmp_path)
    assert queue.enqueue("") is None
    assert queue.enqueue("   ") is None
    assert queue.jobs() == []
