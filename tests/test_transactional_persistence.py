"""Transactional persistence regressions for queue and ref-api state stores.

Failures are injected at the real write boundaries used by
``ref_api.atomic_json`` (JSON dump, file fsync, atomic replace), not by mocking
the high-level enqueue/record methods.  A failed write must not publish a
phantom accepted job/identity/idempotency entry in memory, and a restart must
load only the durable state.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from ref_api.atomic_json import atomic_write_json
from ref_api.show_notes_queue import KIND_DISCOVER, ShowNotesQueue
from ref_api.state_store import IdempotencyStore, UrlIdentityStore


@contextmanager
def _failure(boundary: str):
    """Inject an actual persistence failure at ``boundary``."""
    import ref_api.atomic_json as atomic_json

    if boundary == "dump":
        target = patch.object(
            atomic_json.json, "dump", side_effect=OSError("simulated write failure")
        )
    elif boundary == "fsync":
        target = patch.object(
            atomic_json.os, "fsync", side_effect=OSError("simulated fsync failure")
        )
    elif boundary == "replace":
        target = patch.object(
            atomic_json.os, "replace", side_effect=OSError("simulated replace failure")
        )
    else:  # pragma: no cover - guards the parametrization
        raise AssertionError(f"unknown boundary {boundary}")
    with target:
        yield


def _no_temp_files(directory) -> bool:
    return not list(directory.glob("*.tmp"))


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_queue_enqueue_failure_is_not_visible_and_can_retry(tmp_path, boundary):
    queue = ShowNotesQueue(str(tmp_path / "queue"))

    with _failure(boundary):
        with pytest.raises(OSError):
            queue.enqueue("https://example.org/a")

    assert queue.jobs() == []
    assert ShowNotesQueue(str(tmp_path / "queue")).jobs() == []
    assert _no_temp_files(tmp_path / "queue")

    job_id = queue.enqueue("https://example.org/a")
    assert job_id
    assert len(queue.jobs()) == 1


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_queue_batch_enqueue_failure_is_not_visible(tmp_path, boundary):
    queue = ShowNotesQueue(str(tmp_path / "queue"))

    with _failure(boundary):
        with pytest.raises(OSError):
            queue.enqueue_many(
                ["https://example.org/a", "https://example.org/b"],
                kind=KIND_DISCOVER,
            )

    assert queue.jobs() == []
    assert ShowNotesQueue(str(tmp_path / "queue")).jobs() == []
    queued, skipped = queue.enqueue_many(
        ["https://example.org/a", "https://example.org/b"]
    )
    assert (queued, skipped) == (2, 0)


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_queue_claim_failure_leaves_job_pending(tmp_path, boundary):
    queue = ShowNotesQueue(str(tmp_path / "queue"))
    job_id = queue.enqueue("https://example.org/a")

    with _failure(boundary):
        with pytest.raises(OSError):
            queue.next_pending()

    job = {item["id"]: item for item in queue.jobs()}[job_id]
    assert job["status"] == "pending"
    assert job["attempts"] == 0
    assert ShowNotesQueue(str(tmp_path / "queue")).jobs()[0]["status"] == "pending"

    claimed = queue.next_pending()
    assert claimed["id"] == job_id
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_queue_terminal_transition_failure_is_not_visible(tmp_path, boundary):
    queue = ShowNotesQueue(str(tmp_path / "queue"))
    job_id = queue.enqueue("https://example.org/a")
    queue.next_pending()

    with _failure(boundary):
        with pytest.raises(OSError):
            queue.mark_done(job_id)

    job = {item["id"]: item for item in queue.jobs()}[job_id]
    assert job["status"] == "running"
    assert ShowNotesQueue(str(tmp_path / "queue")).jobs()[0]["status"] == "running"

    queue.mark_done(job_id)
    assert {item["id"]: item for item in queue.jobs()}[job_id]["status"] == "done"


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_queue_retry_transition_failure_is_not_visible(tmp_path, boundary):
    queue = ShowNotesQueue(str(tmp_path / "queue"))
    job_id = queue.enqueue("https://example.org/a")
    queue.next_pending()

    with _failure(boundary):
        with pytest.raises(OSError):
            queue.mark_failed(job_id, "transient")

    job = {item["id"]: item for item in queue.jobs()}[job_id]
    assert job["status"] == "running"
    assert job["last_error"] == ""
    restarted = {item["id"]: item for item in ShowNotesQueue(str(tmp_path / "queue")).jobs()}
    assert restarted[job_id]["status"] == "running"

    queue.mark_failed(job_id, "transient")
    job = {item["id"]: item for item in queue.jobs()}[job_id]
    assert job["status"] == "pending"
    assert job["last_error"] == "transient"


def test_queue_failed_enqueue_preserves_existing_accepted_work(tmp_path):
    queue = ShowNotesQueue(str(tmp_path / "queue"))
    first = queue.enqueue("https://example.org/accepted")

    with _failure("replace"):
        with pytest.raises(OSError):
            queue.enqueue("https://example.org/rejected")

    jobs = {item["id"]: item for item in queue.jobs()}
    assert set(jobs) == {first}
    restarted = ShowNotesQueue(str(tmp_path / "queue"))
    assert {item["id"] for item in restarted.jobs()} == {first}


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_identity_write_failure_is_not_visible(tmp_path, boundary):
    state_dir = tmp_path / "state"
    store = UrlIdentityStore(str(state_dir))
    store.record("https://example.org/keep", "https://example.org/stored-keep")

    with _failure(boundary):
        with pytest.raises(OSError):
            store.record("https://example.org/new", "https://example.org/stored-new")

    assert store.lookup("https://example.org/keep") == "https://example.org/stored-keep"
    assert store.lookup("https://example.org/new") is None

    restarted = UrlIdentityStore(str(state_dir))
    assert restarted.lookup("https://example.org/keep") == "https://example.org/stored-keep"
    assert restarted.lookup("https://example.org/new") is None
    assert _no_temp_files(state_dir)

    store.record("https://example.org/new", "https://example.org/stored-new")
    assert store.lookup("https://example.org/new") == "https://example.org/stored-new"


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_idempotency_begin_failure_is_not_visible(tmp_path, boundary):
    state_dir = tmp_path / "state"
    store = IdempotencyStore(str(state_dir))

    with _failure(boundary):
        with pytest.raises(OSError):
            store.begin(
                "key-1",
                request_hash="hash-1",
                inputs=["https://example.org/a"],
                force=False,
            )

    assert store.get("key-1") is None
    assert IdempotencyStore(str(state_dir)).get("key-1") is None
    assert _no_temp_files(state_dir)

    entry = store.begin(
        "key-1",
        request_hash="hash-1",
        inputs=["https://example.org/a"],
        force=False,
    )
    assert entry["state"] == "processing"


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_idempotency_update_failure_does_not_publish_results(tmp_path, boundary):
    state_dir = tmp_path / "state"
    store = IdempotencyStore(str(state_dir))
    store.begin(
        "key-1",
        request_hash="hash-1",
        inputs=["https://example.org/a"],
        force=False,
    )

    with _failure(boundary):
        with pytest.raises(OSError):
            store.update(
                "key-1",
                results=[{"input": "https://example.org/a"}],
                completed=True,
            )

    entry = store.get("key-1")
    assert entry["state"] == "processing"
    assert entry["results"] == [None]
    restarted = IdempotencyStore(str(state_dir)).get("key-1")
    assert restarted["state"] == "processing"
    assert restarted["results"] == [None]

    completed = store.update(
        "key-1",
        results=[{"input": "https://example.org/a"}],
        completed=True,
    )
    assert completed["state"] == "completed"


@pytest.mark.parametrize("boundary", ["dump", "fsync", "replace"])
def test_idempotency_ambiguous_failure_is_not_visible(tmp_path, boundary):
    state_dir = tmp_path / "state"
    store = IdempotencyStore(str(state_dir))
    store.begin(
        "key-1",
        request_hash="hash-1",
        inputs=["https://example.org/a"],
        force=True,
    )

    with _failure(boundary):
        with pytest.raises(OSError):
            store.mark_ambiguous(
                "key-1",
                results=[None],
                attempts=[{"fingerprint": "sha256:old", "started_at": 1.0}],
                error="ambiguous forced retry",
            )

    entry = store.get("key-1")
    assert entry["state"] == "processing"
    assert entry["attempts"] == [None]
    restarted = IdempotencyStore(str(state_dir)).get("key-1")
    assert restarted["state"] == "processing"
    assert restarted["attempts"] == [None]

    ambiguous = store.mark_ambiguous(
        "key-1",
        results=[None],
        attempts=[{"fingerprint": "sha256:old", "started_at": 1.0}],
        error="ambiguous forced retry",
    )
    assert ambiguous["state"] == "ambiguous"


def test_atomic_write_failure_keeps_previous_file_intact(tmp_path):
    path = tmp_path / "state.json"
    atomic_write_json(str(path), {"version": 1, "value": "old"})

    with _failure("replace"):
        with pytest.raises(OSError):
            atomic_write_json(str(path), {"version": 1, "value": "new"})

    assert path.read_text(encoding="utf-8").strip() == '{"value": "old", "version": 1}'
    assert _no_temp_files(tmp_path)


@pytest.mark.parametrize(
    "store_factory,filename",
    [
        (UrlIdentityStore, "url_identities.json"),
        (IdempotencyStore, "idempotency.json"),
    ],
)
def test_corrupt_state_file_is_never_overwritten(tmp_path, store_factory, filename):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    path = state_dir / filename
    original = b"{ not valid json"
    path.write_bytes(original)

    store = store_factory(str(state_dir))

    with pytest.raises(Exception):
        if store_factory is UrlIdentityStore:
            store.record("https://example.org/a", "https://example.org/b")
        else:
            store.begin(
                "key-1",
                request_hash="hash-1",
                inputs=["https://example.org/a"],
                force=False,
            )

    assert path.read_bytes() == original
    assert _no_temp_files(state_dir)
