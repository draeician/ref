"""Durable, restart-recoverable, deduplicating local work queue for show-note links.

YouTube show-note discovery finds up to ``MAX_YOUTUBE_SHOW_NOTE_LINKS`` outbound
links on a submitted video. Processing those children synchronously used to keep
the ``POST /urls`` response hostage to slow child work (e.g. a discovered
playlist expanding into full video/transcript traversal). Those children are now
enqueued here and processed by a single background worker thread, so the parent's
API result returns immediately.

Design constraints (see ``.codex/tasks/d0c54a91-...``):

* **Durable** -- jobs are persisted as an atomically-rewritten JSON file *beside*
  the archive (``<references>/show_notes_queue/jobs.json``), never inside the git
  repository. Accepted child work survives a service restart.
* **At-least-once / recoverable** -- a job is marked ``running`` only when a
  worker claims it, and ``recover()`` returns any ``running`` job to ``pending``
  on startup, so a crash mid-child is retried.
* **Deduplicating** -- ``enqueue`` skips a URL that already has an unfinished
  (pending/running) job, so repeated/concurrent submissions of the same parent do
  not double-fan-out. Terminal jobs (done/failed) may be re-enqueued by a later
  discovery.
* **Bounded retries/backoff** -- transient failures are retried with exponential
  backoff up to ``MAX_ATTEMPTS``, then left in a visible ``failed`` state.
* **Idempotent archive operations** -- the worker routes every child through
  ``ref_api.service.process_one``, which keeps ``references.md`` appends
  serialized under ``_write_lock`` and returns ``exists`` for already-recorded
  URLs.

The queue is intentionally single-writer/single-process: only the ``ref-api``
process on the archive host drains it, so a process-local ``threading.RLock`` is
sufficient for in-memory consistency, with atomic ``temp + os.replace`` writes
for durability.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QUEUE_DIRNAME = "show_notes_queue"
JOBS_FILENAME = "jobs.json"

# Terminal states are never re-claimed by the worker.
TERMINAL_STATES = frozenset({"done", "failed"})

MAX_ATTEMPTS = 5
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 60.0


class ShowNotesQueue:
    """File-backed, deduplicating queue of show-note child URLs."""

    def __init__(self, queue_dir: str) -> None:
        self.queue_dir = queue_dir
        self.jobs_path = os.path.join(queue_dir, JOBS_FILENAME)
        self._lock = threading.RLock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    # -- persistence -----------------------------------------------------

    def _load(self) -> None:
        """Read jobs from disk once. Missing/corrupt files are treated as empty."""
        if self._loaded:
            return
        self._loaded = True
        data: Any = {}
        try:
            with open(self.jobs_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            data = {}
        if isinstance(data, dict) and isinstance(data.get("jobs"), dict):
            self._jobs = data["jobs"]
        else:
            self._jobs = {}

    def _snapshot(self) -> None:
        """Atomically persist the current job table."""
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
        """Return any ``running`` job to ``pending`` (at-least-once after restart).

        Returns the number of recovered jobs.
        """
        with self._lock:
            self._load()
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

    def enqueue(self, url: str, *, parent_video_id: str = "") -> Optional[str]:
        """Add ``url`` as a pending job unless an unfinished job for it exists.

        Returns the new job id, or ``None`` when the URL was already queued and
        not yet finished (dedup). Terminal jobs are not treated as duplicates.
        """
        key = self._key(url)
        if not key:
            return None
        with self._lock:
            self._load()
            for job in self._jobs.values():
                if job.get("url_key") == key and job.get("status") not in TERMINAL_STATES:
                    return None
            job_id = uuid.uuid4().hex
            now = time.time()
            self._jobs[job_id] = {
                "id": job_id,
                "url": url,
                "url_key": key,
                "parent_video_id": parent_video_id or "",
                "status": "pending",
                "attempts": 0,
                "next_attempt_at": now,
                "last_error": "",
                "enqueued_at": now,
                "updated_at": now,
            }
            self._snapshot()
            return job_id

    def next_pending(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Atomically claim the next runnable job and mark it ``running``."""
        now = time.time() if now is None else now
        with self._lock:
            self._load()
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
            counts: Dict[str, int] = {"pending": 0, "running": 0, "done": 0, "failed": 0}
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
