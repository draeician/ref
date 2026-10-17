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
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

QUEUE_DIRNAME = "show_notes_queue"
JOBS_FILENAME = "jobs.json"

# Job kinds. "discover" jobs fetch a video's show notes; "ingest" jobs record a
# single discovered URL.
KIND_DISCOVER = "discover"
KIND_INGEST = "ingest"

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


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        """Read jobs from disk once.

        A nonexistent file is a fresh queue. An existing file that cannot be
        read, parsed, or validated is marked corrupt; no mutation is allowed
        afterwards and the original bytes are never overwritten.
        """
        if self._loaded:
            return
        self._loaded = True

        try:
            with open(self.jobs_path, "r", encoding="utf-8") as handle:
                raw = handle.read()
        except FileNotFoundError:
            self._jobs = {}
            self._corrupt = False
            self._corrupt_error = ""
            return
        except OSError as exc:  # noqa: BLE001 - permission/IO error is not fresh
            self._mark_corrupt(f"queue file is unreadable: {exc}")
            return

        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:  # noqa: BLE001
            self._mark_corrupt(f"queue file is not valid JSON: {exc}")
            return

        if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
            self._mark_corrupt("queue file schema invalid (missing 'jobs' map)")
            return

        jobs: Dict[str, Dict[str, Any]] = {}
        for job_id, job in data["jobs"].items():
            if not self._valid_job(job_id, job):
                self._mark_corrupt(f"queue file has an invalid job entry ({job_id})")
                return
            jobs[str(job_id)] = self._normalize_job(job)
        self._jobs = jobs
        self._corrupt = False
        self._corrupt_error = ""

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
    def _valid_job(job_id: Any, job: Any) -> bool:
        if not isinstance(job, dict):
            return False
        if not isinstance(job_id, str) or not job_id:
            return False
        if not isinstance(job.get("url"), str) or not job["url"].strip():
            return False
        if job.get("status") not in ALLOWED_STATUSES:
            return False
        return True

    @staticmethod
    def _normalize_job(job: Dict[str, Any]) -> Dict[str, Any]:
        url = str(job.get("url", ""))
        kind = job.get("kind")
        if kind not in (KIND_DISCOVER, KIND_INGEST):
            kind = KIND_INGEST
        now = time.time()
        return {
            "id": str(job.get("id", "")),
            "url": url,
            "url_key": str(job.get("url_key") or url.strip()),
            "parent_video_id": str(job.get("parent_video_id") or ""),
            "kind": kind,
            "status": job.get("status", "pending"),
            "attempts": int(job.get("attempts") or 0),
            "next_attempt_at": _as_float(job.get("next_attempt_at"), now),
            "last_error": str(job.get("last_error") or ""),
            "enqueued_at": _as_float(job.get("enqueued_at"), now),
            "updated_at": _as_float(job.get("updated_at"), now),
        }

    def _check_not_corrupt(self) -> None:
        self._load()
        if self._corrupt:
            raise QueueCorruptError(self._corrupt_error)

    def _prune_terminal(self) -> None:
        """Compact terminal history to ``MAX_TERMINAL_JOBS`` (oldest first)."""
        terminal = [
            job for job in self._jobs.values() if job.get("status") in TERMINAL_STATES
        ]
        if len(terminal) <= MAX_TERMINAL_JOBS:
            return
        terminal.sort(
            key=lambda job: (job.get("updated_at", 0.0), job.get("enqueued_at", 0.0))
        )
        for job in terminal[: len(terminal) - MAX_TERMINAL_JOBS]:
            self._jobs.pop(job["id"], None)

    def _snapshot(self) -> None:
        """Atomically persist the current job table (refuses when corrupt)."""
        if self._corrupt:
            raise QueueCorruptError(self._corrupt_error)
        self._prune_terminal()
        os.makedirs(self.queue_dir, exist_ok=True)
        tmp_path = f"{self.jobs_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"jobs": self._jobs}, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.jobs_path)

    # -- lifecycle -------------------------------------------------------

    def recover(self) -> int:
        """Return any ``running`` job to ``pending`` (at-least-once after restart)."""
        with self._lock:
            self._check_not_corrupt()
            recovered = 0
            now = time.time()
            for job in self._jobs.values():
                if job.get("status") == "running":
                    job["status"] = "pending"
                    job["next_attempt_at"] = now
                    job["updated_at"] = now
                    recovered += 1
            if recovered:
                self._snapshot()
            return recovered

    # -- mutations -------------------------------------------------------

    @staticmethod
    def _key(url: str) -> str:
        return (url or "").strip()

    def enqueue(
        self,
        url: str,
        *,
        parent_video_id: str = "",
        kind: str = KIND_INGEST,
    ) -> Optional[str]:
        """Add a job unless a pending/running/done job for ``url`` exists.

        Returns the new job id, or ``None`` when the URL is already handled
        (dedup). Failed jobs are not treated as duplicates, permitting an
        intentional retry.
        """
        key = self._key(url)
        if not key:
            return None
        with self._lock:
            self._check_not_corrupt()
            for job in self._jobs.values():
                if job.get("url_key") == key and job.get("status") in _DEDUP_STATUSES:
                    return None
            job_id = uuid.uuid4().hex
            now = time.time()
            self._jobs[job_id] = {
                "id": job_id,
                "url": url,
                "url_key": key,
                "parent_video_id": parent_video_id or "",
                "kind": kind,
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": now,
                "last_error": "",
                "enqueued_at": now,
                "updated_at": now,
            }
            self._snapshot()
            return job_id

    def enqueue_many(
        self,
        urls: List[str],
        *,
        parent_video_id: str = "",
        kind: str = KIND_INGEST,
    ) -> Tuple[int, int]:
        """Batch-enqueue ``urls`` with a single snapshot. Returns (queued, skipped)."""
        queued = 0
        skipped = 0
        with self._lock:
            self._check_not_corrupt()
            now = time.time()
            for url in urls:
                key = self._key(url)
                if not key:
                    skipped += 1
                    continue
                if any(
                    job.get("url_key") == key and job.get("status") in _DEDUP_STATUSES
                    for job in self._jobs.values()
                ):
                    skipped += 1
                    continue
                job_id = uuid.uuid4().hex
                self._jobs[job_id] = {
                    "id": job_id,
                    "url": url,
                    "url_key": key,
                    "parent_video_id": parent_video_id or "",
                    "kind": kind,
                    "status": "pending",
                    "attempts": 0,
                    "next_attempt_at": now,
                    "last_error": "",
                    "enqueued_at": now,
                    "updated_at": now,
                }
                queued += 1
            if queued:
                self._snapshot()
            return queued, skipped

    def enqueue_discovery(self, video_url: str, video_id: str) -> Optional[str]:
        """Enqueue a ``discover`` job for a submitted YouTube video."""
        return self.enqueue(video_url, parent_video_id=video_id, kind=KIND_DISCOVER)

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
            job = candidates[0]
            job["status"] = "running"
            job["attempts"] = int(job.get("attempts", 0)) + 1
            job["updated_at"] = now
            self._snapshot()
            return dict(job)

    def mark_done(self, job_id: str) -> None:
        with self._lock:
            self._check_not_corrupt()
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = "done"
            job["last_error"] = ""
            job["updated_at"] = time.time()
            self._snapshot()

    def mark_failed(self, job_id: str, error: str, *, retryable: bool = True) -> None:
        """Record a failure; retry with backoff up to ``MAX_ATTEMPTS``, else terminal."""
        with self._lock:
            self._check_not_corrupt()
            job = self._jobs.get(job_id)
            if job is None:
                return
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
            self._snapshot()

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
