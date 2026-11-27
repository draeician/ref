"""Idempotency crash-recovery regressions.

Each test injects a hard interruption at a real point in the capture pipeline
(not by mocking the idempotency store), restarts the service-side caches, and
replays the same key.  Forced requests must never repeat a possibly committed
write; non-forced requests may safely re-run because capture and discovery are
idempotent.
"""

from __future__ import annotations

import pytest

from ref_api import service
from ref_api.show_notes_queue import KIND_DISCOVER, ShowNotesQueue
from ref_api.state_store import IdempotencyStore
from ref_cli import cli as ref_cli

REDDIT_URL = "https://www.reddit.com/r/example/comments/123/example"
KEY = "crash-key"
HEADER = "# ref-references version=2\n"


class SimulatedCrash(BaseException):
    """Hard interruption not caught by the per-URL Exception boundary."""


@pytest.fixture
def env(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text(HEADER, encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(archive))
    monkeypatch.setattr(service.ref_cli, "BASE", str(tmp_path))
    monkeypatch.setattr(
        service.ref_cli, "TRANSCRIPTS_DIR", str(tmp_path / "transcripts")
    )
    monkeypatch.setattr(
        service.ref_cli,
        "TRANSCRIPT_PENDING_FILE",
        str(tmp_path / "transcripts" / "transcript-pending.md"),
    )
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {"skip_patterns": []})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, cfg: False)
    monkeypatch.setattr(service.ref_cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(service.ref_cli, "get_title_from_url", lambda url: "Example")
    for name in (
        "_queue",
        "_queue_dir",
        "_identity_store",
        "_identity_dir",
        "_idempotency_store",
        "_idempotency_dir",
    ):
        monkeypatch.setattr(service, name, None)
    return tmp_path


def _rows(archive) -> list[str]:
    return [
        line.strip()
        for line in archive.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _restart() -> None:
    """Drop process-local caches so the next call loads durable state."""
    service._queue = None
    service._queue_dir = None
    service._identity_store = None
    service._identity_dir = None
    service._idempotency_store = None
    service._idempotency_dir = None


def _entry(tmp_path) -> dict:
    return IdempotencyStore(str(tmp_path / "ref_api_state")).get(KEY)


def _discover_jobs(tmp_path) -> list[dict]:
    queue = ShowNotesQueue(str(tmp_path / "show_notes_queue"))
    return [
        job
        for job in queue.jobs()
        if job.get("kind") == KIND_DISCOVER and job.get("source") == "reddit"
    ]


def _assert_ambiguous(tmp_path, archive, expected_rows: int) -> None:
    assert _entry(tmp_path)["state"] == "ambiguous"
    assert "ambiguous" in (_entry(tmp_path)["error"] or "").lower()
    assert len(_rows(archive)) == expected_rows


@pytest.mark.parametrize("force", [False, True])
def test_interrupt_before_archive_commit_recovers(env, monkeypatch, force):
    archive = env / "references.md"
    real_process_url = service.ref_cli.process_url
    crashed = {"done": False}

    def crash_once(*args, **kwargs):
        if not crashed["done"]:
            crashed["done"] = True
            raise SimulatedCrash()
        return real_process_url(*args, **kwargs)

    monkeypatch.setattr(service.ref_cli, "process_url", crash_once)

    with pytest.raises(SimulatedCrash):
        service.process_many_idempotent([REDDIT_URL], idempotency_key=KEY, force=force)

    assert _rows(archive) == []
    assert _entry(env)["state"] == "processing"
    _restart()

    results, replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=force
    )
    assert replayed is False
    assert results[0].status == "added"
    assert results[0].primary.archive_confirmed is True
    assert len(_rows(archive)) == 1
    assert _entry(env)["state"] == "completed"


@pytest.mark.parametrize("force", [False, True])
def test_interrupt_after_archive_commit_before_identity(env, monkeypatch, force):
    archive = env / "references.md"
    real_remember = service._remember_identity
    crashed = {"done": False}

    def crash_once(*args, **kwargs):
        if not crashed["done"]:
            crashed["done"] = True
            raise SimulatedCrash()
        return real_remember(*args, **kwargs)

    monkeypatch.setattr(service, "_remember_identity", crash_once)

    with pytest.raises(SimulatedCrash):
        service.process_many_idempotent([REDDIT_URL], idempotency_key=KEY, force=force)

    assert len(_rows(archive)) == 1
    _restart()

    if force:
        with pytest.raises(Exception) as excinfo:
            service.process_many_idempotent(
                [REDDIT_URL], idempotency_key=KEY, force=True
            )
        assert "ambiguous" in str(excinfo.value).lower()
        _assert_ambiguous(env, archive, 1)
        return

    results, _replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=False
    )
    assert results[0].status == "exists"
    assert len(_rows(archive)) == 1


@pytest.mark.parametrize("force", [False, True])
def test_interrupt_after_identity_before_discovery_enqueue(env, monkeypatch, force):
    archive = env / "references.md"
    real_enqueue = service._enqueue_capture_discovery
    crashed = {"done": False}

    def crash_once(*args, **kwargs):
        if not crashed["done"]:
            crashed["done"] = True
            raise SimulatedCrash()
        return real_enqueue(*args, **kwargs)

    monkeypatch.setattr(service, "_enqueue_capture_discovery", crash_once)

    with pytest.raises(SimulatedCrash):
        service.process_many_idempotent([REDDIT_URL], idempotency_key=KEY, force=force)

    assert len(_rows(archive)) == 1
    assert _discover_jobs(env) == []
    _restart()

    if force:
        with pytest.raises(Exception) as excinfo:
            service.process_many_idempotent(
                [REDDIT_URL], idempotency_key=KEY, force=True
            )
        assert "ambiguous" in str(excinfo.value).lower()
        _assert_ambiguous(env, archive, 1)
        return

    results, _replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=False
    )
    assert results[0].status == "exists"
    assert results[0].discovery.status in {"queued", "already_queued"}
    assert len(_discover_jobs(env)) == 1
    assert len(_rows(archive)) == 1


@pytest.mark.parametrize("force", [False, True])
def test_interrupt_after_discovery_enqueue_before_result(env, monkeypatch, force):
    archive = env / "references.md"
    real_enqueue = service._enqueue_capture_discovery
    crashed = {"done": False}

    def crash_after_enqueue(*args, **kwargs):
        result = real_enqueue(*args, **kwargs)
        if not crashed["done"]:
            crashed["done"] = True
            raise SimulatedCrash()
        return result

    monkeypatch.setattr(service, "_enqueue_capture_discovery", crash_after_enqueue)

    with pytest.raises(SimulatedCrash):
        service.process_many_idempotent([REDDIT_URL], idempotency_key=KEY, force=force)

    assert len(_rows(archive)) == 1
    assert len(_discover_jobs(env)) == 1
    _restart()

    if force:
        with pytest.raises(Exception) as excinfo:
            service.process_many_idempotent(
                [REDDIT_URL], idempotency_key=KEY, force=True
            )
        assert "ambiguous" in str(excinfo.value).lower()
        _assert_ambiguous(env, archive, 1)
        assert len(_discover_jobs(env)) == 1
        return

    results, _replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=False
    )
    assert results[0].status == "exists"
    assert results[0].discovery.status in {"queued", "already_queued"}
    assert len(_discover_jobs(env)) == 1
    assert len(_rows(archive)) == 1


@pytest.mark.parametrize("force", [False, True])
def test_interrupt_during_multi_url_keeps_positional_binding(env, monkeypatch, force):
    archive = env / "references.md"
    first = "https://example.org/first"
    second = "https://example.org/second"
    real_remember = service._remember_identity
    crashed = {"done": False}

    def crash_on_second(original, target, stored_url):
        if original == second and not crashed["done"]:
            crashed["done"] = True
            raise SimulatedCrash()
        return real_remember(original, target, stored_url)

    monkeypatch.setattr(service, "_remember_identity", crash_on_second)

    with pytest.raises(SimulatedCrash):
        service.process_many_idempotent(
            [first, second], idempotency_key=KEY, force=force
        )

    assert len(_rows(archive)) == 2
    stored = _entry(env)["results"]
    assert isinstance(stored[0], dict)
    assert stored[0]["input"] == first
    assert stored[1] is None
    _restart()

    if force:
        with pytest.raises(Exception) as excinfo:
            service.process_many_idempotent(
                [first, second], idempotency_key=KEY, force=True
            )
        assert "ambiguous" in str(excinfo.value).lower()
        assert _entry(env)["state"] == "ambiguous"
        assert len(_rows(archive)) == 2
        return

    results, _replayed = service.process_many_idempotent(
        [first, second], idempotency_key=KEY, force=False
    )
    assert [result.input for result in results] == [first, second]
    assert [result.status for result in results] == ["added", "exists"]
    assert len(_rows(archive)) == 2


@pytest.mark.parametrize("force", [False, True])
def test_response_lost_after_completion_replays_without_duplicate(env, force):
    archive = env / "references.md"

    first_results, first_replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=force
    )
    assert first_replayed is False
    assert first_results[0].status == "added"
    assert len(_rows(archive)) == 1
    assert len(_discover_jobs(env)) == 1

    _restart()
    replayed_results, replayed = service.process_many_idempotent(
        [REDDIT_URL], idempotency_key=KEY, force=force
    )
    assert replayed is True
    assert replayed_results[0].input == REDDIT_URL
    assert replayed_results[0].status == first_results[0].status
    if not force:
        # force=True on the first request may legitimately add one row only;
        # replay never writes again.
        assert len(_rows(archive)) == 1
    assert len(_rows(archive)) == 1
    assert len(_discover_jobs(env)) == 1
