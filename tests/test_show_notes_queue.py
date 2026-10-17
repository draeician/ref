"""Unit tests for the durable show-note work queue."""

from __future__ import annotations

import json
import os

from ref_api.show_notes_queue import MAX_ATTEMPTS, ShowNotesQueue


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
    assert os.path.exists(queue.jobs_path)


def test_enqueue_dedupes_unfinished_duplicate(tmp_path):
    queue = _new_queue(tmp_path)
    first = queue.enqueue("https://example.org/a")
    second = queue.enqueue("https://example.org/a")
    assert first is not None
    assert second is None
    assert len(queue.jobs()) == 1


def test_enqueue_allows_reenqueue_after_terminal(tmp_path):
    queue = _new_queue(tmp_path)
    first = queue.enqueue("https://example.org/a")
    queue.mark_done(first)
    second = queue.enqueue("https://example.org/a")
    assert second is not None
    assert second != first
    assert len(queue.jobs()) == 2


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
    assert queue.unfinished_count() == 2


def test_corrupt_jobs_file_treated_as_empty(tmp_path):
    queue = _new_queue(tmp_path)
    os.makedirs(queue.queue_dir, exist_ok=True)
    with open(queue.jobs_path, "w", encoding="utf-8") as handle:
        handle.write("{ not valid json")
    recovered = queue.recover()
    assert recovered == 0
    assert queue.jobs() == []


def test_enqueue_rejects_empty_url(tmp_path):
    queue = _new_queue(tmp_path)
    assert queue.enqueue("") is None
    assert queue.enqueue("   ") is None
    assert queue.jobs() == []
