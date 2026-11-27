"""Durable, restart-recoverable, deduplicating local work queue for show-note links.

YouTube show-note processing is split into two background job kinds so a parent's
``POST /urls`` never waits on slow provider/network work:

* ``discover`` -- the submitted YouTube video. The worker fetches its metadata
  card, extracts outbound links, and enqueues ``ingest`` jobs for each link.
* ``ingest`` -- a discovered child URL. The worker records it in the archive
  (or, for a discovered playlist, records the playlist link without expansion).

Design constraints (see ``.codex/tasks/d0c54a91-...`` and
``.codex/tasks/7e4c9b12-...``):

* **Durable / fail-closed** -- jobs persist as an atomically-rewritten JSON file
  beside the archive (``<references>/show_notes_queue/jobs.json``), never in git.
  A fresh (nonexistent) file is an empty queue; an existing file that is
  unreadable, not valid JSON, or schema-invalid is treated as *corrupt*: the
  queue refuses to mutate or overwrite it and surfaces the failure, so accepted
  work is never silently destroyed.
* **At-least-once / recoverable** -- a job is ``running`` only while a worker
  holds it; ``recover()`` returns any ``running`` job to ``pending`` on startup.
* **Deduplicating + bounded** -- ``enqueue`` skips a URL that already has a
  pending/running/done job, so repeated or concurrent parent submissions do not
  redo completed work. Failed jobs may be re-enqueued (intentional retry).
  Terminal history is compacted to a bounded size so the table cannot grow
  without limit.
* **Bounded retries/backoff** -- transient failures retry with exponential
  backoff up to ``MAX_ATTEMPTS``, then remain in a visible ``failed`` state.
* **Single-process** -- only the ``ref-api`` process drains the queue, so a
  process-local ``threading.RLock`` is sufficient, with atomic
  ``temp + os.replace`` writes for durability.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from ref_api.atomic_json import atomic_write_json

logger = logging.getLogger(__name__)

QUEUE_DIRNAME = "show_notes_queue"
JOBS_FILENAME = "jobs.json"

# Job kinds. "discover" jobs fetch a video's show notes; "ingest" jobs record a
# single discovered URL.
KIND_DISCOVER = "discover"
KIND_INGEST = "ingest"

# Discovery source. ``source`` is an additive, optional field: existing snapshots
# have no value and therefore load as YouTube, while new Reddit discovery jobs
# use the same ``discover`` kind so an older ref-api can still read the table
# (it degrades to a no-op YouTube discovery instead of corrupting the queue).
SOURCE_YOUTUBE = "youtube"
SOURCE_REDDIT = "reddit"
ALLOWED_SOURCES = frozenset({SOURCE_YOUTUBE, SOURCE_REDDIT})

# Non-terminal states are never re-claimed by the worker.
TERMINAL_STATES = frozenset({"done", "failed"})
# A URL with any of these statuses is treated as already-handled (dedup).
_DEDUP_STATUSES = frozenset({"pending", "running", "done"})

ALLOWED_STATUSES = frozenset({"pending", "running", "done", "failed"})

MAX_ATTEMPTS = 5
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 60.0

# Bound on retained terminal (done/failed) job history. Older terminal jobs are
# pruned (oldest first) so the JSON table cannot grow without limit.
MAX_TERMINAL_JOBS = 1000


class QueueCorruptError(RuntimeError):
    """The on-disk queue exists but is unreadable, malformed, or schema-invalid."""


class ShowNotesQueue:
    """File-backed, deduplicating queue of show-note discovery/ingest jobs."""

    def __init__(self, queue_dir: str) -> None:
        self.queue_dir = queue_dir
        self.jobs_path = os.path.join(queue_dir, JOBS_FILENAME)
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self._corrupt = False
        self._corrupt_error = ""

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        """Read jobs from disk once, failing closed on any malformed file.

        A nonexistent file is a fresh queue. An existing file that cannot be
        read, decoded, parsed, or fully validated is marked corrupt; no mutation
        is allowed afterwards and the original bytes are never overwritten.

        ``_loaded`` is set only after validation completes (success or an
        explicit corrupt state), so a failed load can never leave the queue in a
        state where a later ``enqueue`` skips loading and silently overwrites the
        original ``jobs.json``.
        """
        if self._loaded:
            return

        try:
            with open(self.jobs_path, "rb") as handle:
                raw_bytes = handle.read()
        except FileNotFoundError:
            self._jobs = {}
            self._corrupt = False
            self._corrupt_error = ""
            self._loaded = True
            return
        except OSError as exc:  # noqa: BLE001 - permission/IO error is not fresh
            self._mark_corrupt(f"queue file is unreadable: {exc}")
            self._loaded = True
            return

        # Decode, parse and validate under one boundary so UnicodeDecodeError,
        # JSONDecodeError and any per-field ValueError/TypeError all fail closed.
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
            jobs = self._parse_jobs(data)
        except Exception as exc:  # noqa: BLE001 - any malformation is corrupt
            self._mark_corrupt(f"queue file is malformed: {exc}")
            self._loaded = True
            return

        self._jobs = jobs
        self._corrupt = False
        self._corrupt_error = ""
        self._loaded = True

    def _mark_corrupt(self, message: str) -> None:
        self._corrupt = True
        self._corrupt_error = message
        self._jobs = {}
        logger.error(
            "show-notes queue is corrupt and has been taken read-only; "
            "refusing to overwrite %s. Operator action required: inspect and "
            "remove/rename the file if it is unrecoverable. (%s)",
            self.jobs_path, message,
        )

    @staticmethod
    def _parse_jobs(data: Any) -> Dict[str, Dict[str, Any]]:
        """Validate the top-level schema and every job, returning normalized jobs."""
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
            raise ValueError("missing 'jobs' map")
        jobs: Dict[str, Dict[str, Any]] = {}
        for job_id, job in data["jobs"].items():
            if not isinstance(job_id, str) or not job_id:
                raise ValueError(f"invalid job id {job_id!r}")
            jobs[job_id] = ShowNotesQueue._normalize_job(job_id, job)
        return jobs

    @staticmethod
    def _normalize_job(job_id: str, job: Any) -> Dict[str, Any]:
        """Fully validate one persisted job and return its normalized form.

        Raises ``ValueError`` on any type/range/kind/status/id inconsistency so
        the caller's fail-closed boundary marks the whole queue corrupt rather
        than silently repairing (or dropping) an invalid entry. Missing optional
        fields default; present-but-wrong-typed fields are corrupt.
        """
        if not isinstance(job, dict):
            raise ValueError(f"job {job_id!r} is not an object")

        # The outer key is authoritative; a mismatched inner id is corrupt.
        inner_id = job.get("id")
        if inner_id is not None and (
            not isinstance(inner_id, str) or inner_id != job_id
        ):
            raise ValueError(f"job {job_id!r} has mismatched id {inner_id!r}")

        url = job.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"job {job_id!r} has no valid url")
        url = url.strip()

        status = job.get("status", "pending")
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            raise ValueError(f"job {job_id!r} has invalid status {status!r}")

        kind = job.get("kind")
        if kind is None:
            kind = KIND_INGEST
        if kind not in (KIND_DISCOVER, KIND_INGEST):
            raise ValueError(f"job {job_id!r} has invalid kind {kind!r}")

        source = job.get("source")
        if source is None:
            source = SOURCE_YOUTUBE
        elif source not in ALLOWED_SOURCES:
            raise ValueError(f"job {job_id!r} has invalid source {source!r}")

        attempts = job.get("attempts")
        if attempts is None:
            attempts = 0
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise ValueError(f"job {job_id!r} has invalid attempts {attempts!r}")

        url_key = job.get("url_key")
        if url_key is None:
            url_key = url
        elif not isinstance(url_key, str):
            raise ValueError(f"job {job_id!r} has invalid url_key {url_key!r}")

        parent_video_id = job.get("parent_video_id")
        if parent_video_id is None:
            parent_video_id = ""
        elif not isinstance(parent_video_id, str):
            raise ValueError(
                f"job {job_id!r} has invalid parent_video_id {parent_video_id!r}"
            )

        last_error = job.get("last_error")
        if last_error is None:
            last_error = ""
        elif not isinstance(last_error, str):
            raise ValueError(f"job {job_id!r} has invalid last_error {last_error!r}")

        now = time.time()

        def _ts(value: Any, field: str) -> float:
            if value is None:
                return now
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"job {job_id!r} has invalid {field} {value!r}")
            result = float(value)
            # ``json.loads`` accepts NaN/Infinity/-Infinity and parses ``1e309``
            # as an infinite float; a non-finite deadline would silently strand a
            # pending job forever (``NaN <= now`` is never true). Reject it.
            if not math.isfinite(result):
                raise ValueError(f"job {job_id!r} has non-finite {field} {value!r}")
            return result

        return {
            "id": job_id,
            "url": url,
            "url_key": url_key,
            "parent_video_id": parent_video_id,
            "kind": kind,
            "source": source,
            "status": status,
            "attempts": attempts,
            "next_attempt_at": _ts(job.get("next_attempt_at"), "next_attempt_at"),
            "last_error": last_error,
            "enqueued_at": _ts(job.get("enqueued_at"), "enqueued_at"),
            "updated_at": _ts(job.get("updated_at"), "updated_at"),
        }

    def _check_not_corrupt(self) -> None:
        self._load()
        if self._corrupt:
            raise QueueCorruptError(self._corrupt_error)

    def _prune_terminal(self, jobs: Dict[str, Dict[str, Any]]) -> None:
        """Compact terminal history to ``MAX_TERMINAL_JOBS`` (oldest first)."""
        terminal = [
            job for job in jobs.values() if job.get("status") in TERMINAL_STATES
        ]
        if len(terminal) <= MAX_TERMINAL_JOBS:
            return
        terminal.sort(
            key=lambda job: (job.get("updated_at", 0.0), job.get("enqueued_at", 0.0))
        )
        for job in terminal[: len(terminal) - MAX_TERMINAL_JOBS]:
            jobs.pop(job["id"], None)

    def _copy_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Return a shallow copy of the job table suitable for mutation."""
        return {job_id: dict(job) for job_id, job in self._jobs.items()}

    def _commit(self, jobs: Dict[str, Dict[str, Any]]) -> None:
        """Persist ``jobs`` first, then publish it as the in-memory table.

        Copy-on-write: a failed write leaves the previous in-memory snapshot
        untouched, so a phantom accepted job is never visible to a later request
        or to the worker.
        """
        if self._corrupt:
            raise QueueCorruptError(self._corrupt_error)
        self._prune_terminal(jobs)
        atomic_write_json(self.jobs_path, {"jobs": jobs})
        self._jobs = jobs

    # -- lifecycle -------------------------------------------------------

    def recover(self) -> int:
        """Return any ``running`` job to ``pending`` (at-least-once after restart)."""
        with self._lock:
            self._check_not_corrupt()
            jobs = self._copy_jobs()
            recovered = 0
            now = time.time()
            for job in jobs.values():
                if job.get("status") == "running":
                    job["status"] = "pending"
                    job["next_attempt_at"] = now
                    job["updated_at"] = now
                    recovered += 1
            if recovered:
                self._commit(jobs)
            return recovered

    # -- mutations -------------------------------------------------------

    @staticmethod
    def _key(url: str) -> str:
        return (url or "").strip()

    @staticmethod
    def _is_duplicate(job: Dict[str, Any], key: str, kind: str) -> bool:
        """True when ``job`` already covers this URL for ``kind``.

        Ingest keeps the historical URL-wide dedup. Discovery is deduped only
        against an existing discovery job, so submitting a URL that was already
        ingested as a show-note child can still discover its outbound links.
        """
        if job.get("url_key") != key or job.get("status") not in _DEDUP_STATUSES:
            return False
        if kind == KIND_DISCOVER:
            return job.get("kind") == KIND_DISCOVER
        return True

    def enqueue(
        self,
        url: str,
        *,
        parent_video_id: str = "",
        kind: str = KIND_INGEST,
        source: str = SOURCE_YOUTUBE,
    ) -> Optional[str]:
        """Add a job unless a pending/running/done job for ``url`` exists.

        Returns the new job id, or ``None`` when the URL is already handled
        (dedup). Failed jobs are not treated as duplicates, permitting an
        intentional retry.
        """
        key = self._key(url)
        if not key:
            return None
        if source not in ALLOWED_SOURCES:
            raise ValueError(f"Unsupported job source: {source!r}")
        with self._lock:
            self._check_not_corrupt()
            jobs = self._copy_jobs()
            for job in jobs.values():
                if self._is_duplicate(job, key, kind):
                    return None
            job_id = uuid.uuid4().hex
            now = time.time()
            jobs[job_id] = {
                "id": job_id,
                "url": url,
                "url_key": key,
                "parent_video_id": parent_video_id or "",
                "kind": kind,
                "source": source,
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": now,
                "last_error": "",
                "enqueued_at": now,
                "updated_at": now,
            }
            self._commit(jobs)
            return job_id

    def enqueue_many(
        self,
        urls: List[str],
        *,
        parent_video_id: str = "",
        kind: str = KIND_INGEST,
        source: str = SOURCE_YOUTUBE,
    ) -> Tuple[int, int]:
        """Batch-enqueue ``urls`` with a single snapshot. Returns (queued, skipped)."""
        if source not in ALLOWED_SOURCES:
            raise ValueError(f"Unsupported job source: {source!r}")
        queued = 0
        skipped = 0
        with self._lock:
            self._check_not_corrupt()
            jobs = self._copy_jobs()
            now = time.time()
            for url in urls:
                key = self._key(url)
                if not key:
                    skipped += 1
                    continue
                if any(
                    self._is_duplicate(job, key, kind)
                    for job in jobs.values()
                ):
                    skipped += 1
                    continue
                job_id = uuid.uuid4().hex
                jobs[job_id] = {
                    "id": job_id,
                    "url": url,
                    "url_key": key,
                    "parent_video_id": parent_video_id or "",
                    "kind": kind,
                    "source": source,
                    "status": "pending",
                    "attempts": 0,
                    "next_attempt_at": now,
                    "last_error": "",
                    "enqueued_at": now,
                    "updated_at": now,
                }
                queued += 1
            if queued:
                self._commit(jobs)
            return queued, skipped

    def enqueue_discovery(
        self,
        video_url: str,
        video_id: str,
        *,
        source: str = SOURCE_YOUTUBE,
    ) -> Optional[str]:
        """Enqueue a ``discover`` job for a submitted YouTube/Reddit URL."""
        return self.enqueue(
            video_url,
            parent_video_id=video_id,
            kind=KIND_DISCOVER,
            source=source,
        )

    def find_job(self, url: str, *, kind: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the newest job for ``url`` (optionally filtered by kind)."""
        key = self._key(url)
        if not key:
            return None
        with self._lock:
            self._load()
            matches = [
                job
                for job in self._jobs.values()
                if job.get("url_key") == key and (kind is None or job.get("kind") == kind)
            ]
            if not matches:
                return None
            matches.sort(
                key=lambda job: (job.get("updated_at", 0.0), job.get("id", "")),
                reverse=True,
            )
            return dict(matches[0])

    def next_pending(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Atomically claim the next runnable job and mark it ``running``."""
        now = time.time() if now is None else now
        with self._lock:
            self._check_not_corrupt()
            candidates = [
                job
                for job in self._jobs.values()
                if job.get("status") == "pending"
                and job.get("next_attempt_at", 0.0) <= now
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda job: (job.get("enqueued_at", 0.0), job.get("id", "")))
            claimed_id = candidates[0]["id"]
            jobs = self._copy_jobs()
            claimed = jobs[claimed_id]
            claimed["status"] = "running"
            claimed["attempts"] = int(claimed.get("attempts", 0)) + 1
            claimed["updated_at"] = now
            self._commit(jobs)
            return dict(claimed)

    def mark_done(self, job_id: str) -> None:
        with self._lock:
            self._check_not_corrupt()
            if job_id not in self._jobs:
                return
            jobs = self._copy_jobs()
            job = jobs[job_id]
            job["status"] = "done"
            job["last_error"] = ""
            job["updated_at"] = time.time()
            self._commit(jobs)

    def mark_failed(self, job_id: str, error: str, *, retryable: bool = True) -> None:
        """Record a failure; retry with backoff up to ``MAX_ATTEMPTS``, else terminal."""
        with self._lock:
            self._check_not_corrupt()
            if job_id not in self._jobs:
                return
            jobs = self._copy_jobs()
            job = jobs[job_id]
            now = time.time()
            attempts = int(job.get("attempts", 0))
            job["last_error"] = (error or "")[:2000]
            if retryable and attempts < MAX_ATTEMPTS:
                delay = min(
                    RETRY_MAX_DELAY_SECONDS,
                    RETRY_BASE_DELAY_SECONDS * (2 ** (attempts - 1)),
                )
                job["status"] = "pending"
                job["next_attempt_at"] = now + delay
            else:
                job["status"] = "failed"
                job["next_attempt_at"] = now
            job["updated_at"] = now
            self._commit(jobs)

    def rollback_blockers(self) -> List[Dict[str, Any]]:
        """Reddit discovery jobs whose metadata an older API cannot preserve.

        Older ref-api releases reconstruct jobs in ``_normalize_job`` without the
        additive ``source`` field.  Two losses follow:

        * A pending/running Reddit ``discover`` job is read as a non-video
          YouTube job, consumed as a no-op and marked ``done``.
        * On the older build's next snapshot write (for example ``recover()`` or
          any enqueue), every job -- including a terminal ``failed`` one -- is
          rewritten without ``source``, permanently losing its Reddit
          provenance.

        Downgrade is therefore blocked while any Reddit discovery job is
        ``pending``, ``running`` or ``failed``.  A ``done`` job has no
        outstanding work, so losing its source is harmless.  ``QueueCorruptError``
        is raised when the queue cannot be read.
        """
        with self._lock:
            self._check_not_corrupt()
            return [
                dict(job)
                for job in self._jobs.values()
                if job.get("kind") == KIND_DISCOVER
                and job.get("source") == SOURCE_REDDIT
                and job.get("status") in {"pending", "running", "failed"}
            ]

    # -- introspection ---------------------------------------------------

    def stats(self) -> Dict[str, int]:
        with self._lock:
            self._load()
            counts: Dict[str, int] = {
                "pending": 0,
                "running": 0,
                "done": 0,
                "failed": 0,
                "corrupt": 1 if self._corrupt else 0,
            }
            for job in self._jobs.values():
                status = job.get("status", "pending")
                counts[status] = counts.get(status, 0) + 1
            return counts

    def unfinished_count(self) -> int:
        counts = self.stats()
        return counts.get("pending", 0) + counts.get("running", 0)

    def jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            return [dict(job) for job in self._jobs.values()]

    def is_corrupt(self) -> bool:
        with self._lock:
            self._load()
            return self._corrupt

    def corrupt_error(self) -> str:
        with self._lock:
            self._load()
            return self._corrupt_error

    def has_unfinished(self, url: str) -> bool:
        """True when ``url`` has an unfinished (pending/running) job."""
        key = self._key(url)
        if not key:
            return False
        with self._lock:
            self._load()
            return any(
                job.get("url_key") == key and job.get("status") not in TERMINAL_STATES
                for job in self._jobs.values()
            )
