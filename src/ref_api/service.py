"""Service layer: wrap ref_cli.cli.process_url for HTTP ingest."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from ref_cli import cli as ref_cli
from ref_api.schemas import SearchHit, TranscriptResult, UrlResult, UrlStatus
from ref_api.show_notes_queue import (
    KIND_DISCOVER,
    KIND_INGEST,
    QueueCorruptError,
    ShowNotesQueue,
)

logger = logging.getLogger(__name__)
# Uvicorn often leaves the root logger at WARNING. Opt in to INFO for
# show-note discovery so journalctl includes each URL, job id and the queued
# summary without turning on verbose logging across the whole process.
logger.setLevel(logging.INFO)

# Serialize writes to references.md across concurrent requests. This aliases the
# CLI's own archive lock (used by its write primitives) so service-level file
# operations (backup, transcript update) serialize with ``process_url``
# appends/rewrites, while slow network/provider work runs *outside* the lock.
_write_lock = ref_cli._archive_lock

# Thread-safe stdout capture. ``process_url`` reports its result via print(); now
# that callers may run slow provider work concurrently, a global
# ``contextlib.redirect_stdout`` would race. This proxy routes ``print()`` to a
# per-thread buffer when one is set and otherwise to the real stdout.
_stdout_proxy: Optional["_ThreadLocalStdout"] = None
_stdout_proxy_lock = threading.Lock()


class _ThreadLocalStdout:
    """Route ``write``/``flush`` to a per-thread buffer when set, else real stdout."""

    def __init__(self, real):
        self._real = real
        self._local = threading.local()

    def _target(self):
        buf = getattr(self._local, "capture", None)
        return buf if buf is not None else self._real

    def write(self, s: str) -> None:
        self._target().write(s)

    def flush(self) -> None:
        self._target().flush()

    def isatty(self) -> bool:
        return self._target().isatty()

    def fileno(self) -> int:
        return self._real.fileno()

    def __getattr__(self, name: str):
        return getattr(self._real, name)


def _get_stdout_proxy() -> "_ThreadLocalStdout":
    """Return the process-wide proxy, (re)installing it if stdout was swapped."""
    import sys

    global _stdout_proxy
    with _stdout_proxy_lock:
        if _stdout_proxy is None or sys.stdout is not _stdout_proxy:
            _stdout_proxy = _ThreadLocalStdout(sys.stdout)
            sys.stdout = _stdout_proxy
        return _stdout_proxy


@contextlib.contextmanager
def _capture_stdout(buf: io.StringIO):
    """Capture this thread's ``print`` output into ``buf`` without a global redirect."""
    proxy = _get_stdout_proxy()
    previous = getattr(proxy._local, "capture", None)
    proxy._local.capture = buf
    try:
        yield
    finally:
        proxy._local.capture = previous


def _classify_stdout(stdout: str) -> UrlStatus:
    """Map process_url stdout to a coarse status without changing the CLI."""
    text = (stdout or "").strip()
    lower = text.lower()
    if "already recorded" in lower:
        return "exists"
    if lower.startswith("error:") or "invalid url" in lower or "dead link" in lower:
        return "error"
    if text:
        # Successful adds print a pipe-delimited reference line.
        return "added"
    return "error"


# Bound automatic fan-out per API request. Manual extraction has no such cap.
MAX_YOUTUBE_SHOW_NOTE_LINKS = 50

# Directory (beside references.md) that holds the durable show-note queue. This
# is runtime archive state, not version-controlled repository content.
_QUEUE_DIRNAME = "show_notes_queue"

# Background worker singleton + start/stop serialization.
_worker: Optional["_ShowNotesWorker"] = None
_worker_lock = threading.Lock()

# Set when ``start_show_notes_worker`` is called while the previous worker is
# still draining (a prior ``stop_show_notes_worker`` timed out). The exiting
# worker then hands off to a successor so the queue never stalls silently.
_restart_pending = False

# Lazily-constructed queue, keyed to the current archive location so tests that
# repoint ``ref_cli.UNIFIED`` to a temp path get an isolated queue.
_queue: Optional[ShowNotesQueue] = None
_queue_dir: Optional[str] = None
_queue_lock = threading.Lock()


def _queue_directory() -> str:
    """Absolute path of the show-note queue directory beside references.md."""
    return os.path.join(
        os.path.dirname(os.path.abspath(ref_cli.UNIFIED)), _QUEUE_DIRNAME
    )


def _get_queue() -> ShowNotesQueue:
    """Return the (lazily-created) durable queue for the current archive."""
    global _queue, _queue_dir
    current = _queue_directory()
    with _queue_lock:
        if _queue is None or _queue_dir != current:
            _queue = ShowNotesQueue(current)
            _queue_dir = current
        return _queue


def queue_status() -> Dict[str, int]:
    """Return the current show-note queue counts for observability."""
    queue = _get_queue()
    counts = queue.stats()
    counts["unfinished"] = counts.get("pending", 0) + counts.get("running", 0)
    return counts


def _discover_youtube_show_note_links(
    video_url: str,
) -> tuple[Optional[str], List[str], str, int]:
    """Return ``(video_id, links, error_summary, chapter_count)`` for a YouTube URL.

    ``video_id`` is None when the URL is not a YouTube video; ``error_summary``
    is non-empty when metadata retrieval failed (links will be empty).
    """
    from ref_cli.youtube_extract import (
        chapters_from_description,
        outbound_urls,
        read_video_card,
        youtube_video_id,
    )

    video_id = youtube_video_id(video_url)
    if not video_id:
        return None, [], "", 0

    base = os.path.dirname(os.path.abspath(ref_cli.UNIFIED))
    try:
        card = read_video_card(video_id, base)
        description = card.get("description") or ""
        if not isinstance(description, str):
            description = ""
        # Chapter markers are never submitted: outbound_urls finds URLs only.
        chapter_count = len(chapters_from_description(description))
        links = outbound_urls(card, video_id)
    except Exception as exc:  # noqa: BLE001 - best-effort metadata retrieval
        logger.warning("YouTube notes: unavailable video_id=%s reason=%s", video_id, exc)
        return video_id, [], f"YouTube notes: unavailable for {video_id} ({exc})", 0

    logger.info(
        "YouTube notes: metadata video_id=%s source=%s description_chars=%d "
        "timestamps_ignored=%d outbound_links=%d",
        video_id, card.get("source") or "cache", len(description),
        chapter_count, len(links),
    )
    return video_id, links, "", chapter_count


def _enqueue_youtube_discovery(video_url: str, video_id: str) -> str:
    """Enqueue a background ``discover`` job for a submitted YouTube video.

    Card fetch + link extraction is *not* performed here: it runs on the worker,
    so a slow or uncached card access cannot delay the parent ``POST /urls``
    response. Returns a one-line summary (empty when already queued/done).
    """
    queue = _get_queue()
    try:
        job_id = queue.enqueue_discovery(video_url, video_id)
    except QueueCorruptError as exc:
        logger.error("YouTube notes: queue corrupt, discovery not queued: %s", exc)
        return f"YouTube notes: discovery not queued (queue corrupt): {exc}"
    if job_id:
        logger.info(
            "YouTube notes: discovery queued video_id=%s job=%s", video_id, job_id
        )
        return f"YouTube notes: discovery queued video_id={video_id} job={job_id}"
    logger.info("YouTube notes: discovery already queued/done video_id=%s", video_id)
    return ""


def process_one(
    raw_input: str,
    force: bool = False,
    *,
    _discover_youtube_links: bool = True,
    _suppress_playlist_expansion: bool = False,
) -> UrlResult:
    """
    Apply skip patterns, convert YouTube video IDs, then call process_url.

    Archive writes are serialized inside ``ref_cli`` (its ``_archive_lock``), not
    by a lock held across the whole ``process_url`` call, so slow provider/network
    work for one URL does not block another caller's archive write. A parent
    YouTube capture only *enqueues* a background ``discover`` job; show-note
    links are extracted and their children enqueued by the worker, off the
    request path.

    ``_suppress_playlist_expansion`` is set only by the show-note worker so a
    discovered playlist link is recorded without full playlist traversal.
    """
    original = raw_input.strip()
    if not original:
        return UrlResult(
            input=raw_input,
            url=raw_input,
            status="error",
            message="Empty URL",
            output="",
        )

    config = ref_cli.load_config()
    if ref_cli.should_skip_url(original, config):
        return UrlResult(
            input=original,
            url=original,
            status="skipped",
            message="Matches skip pattern",
            output="",
        )

    if ref_cli.is_youtube_video_id(original):
        target = ref_cli.convert_video_id_to_url(original)
    else:
        target = original

    buf = io.StringIO()
    try:
        with _capture_stdout(buf):
            if _suppress_playlist_expansion and _is_youtube_playlist_url(target):
                ref_cli.record_youtube_playlist_link(target, force)
            else:
                ref_cli.process_url(target, force)
        output = buf.getvalue().strip()
        status = _classify_stdout(output)
        if _discover_youtube_links and status in {"added", "exists"}:
            from ref_cli.youtube_extract import youtube_video_id

            video_id = youtube_video_id(target)
            if video_id:
                summary = _enqueue_youtube_discovery(target, video_id)
                if summary:
                    output = f"{output}\n{summary}" if output else summary
        message = {
            "added": "Recorded",
            "exists": "Already recorded",
            "error": output.splitlines()[0] if output else "Processing failed",
            "skipped": "Skipped",
        }.get(status, "")
        return UrlResult(
            input=original,
            url=target,
            status=status,
            message=message,
            output=output,
        )
    except Exception as exc:  # noqa: BLE001 - surface as per-URL error when possible
        output = buf.getvalue().strip()
        logger.exception("Failed to process URL %s", target)
        return UrlResult(
            input=original,
            url=target,
            status="error",
            message=str(exc),
            output=output,
        )


def _is_youtube_playlist_url(url: str) -> bool:
    """Local wrapper so the service does not import youtube_extract at module load."""
    from ref_cli.youtube_extract import is_youtube_playlist_url

    return is_youtube_playlist_url(url)


def _process_queued_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Dispatch one claimed show-note job by kind, then record its terminal state."""
    if job.get("kind") == KIND_DISCOVER:
        _process_discovery_job(queue, job)
    else:
        _process_ingest_job(queue, job)


def _process_discovery_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Fetch a video's show notes (network, no lock) and enqueue its child links."""
    job_id = job.get("id", "")
    video_url = job.get("url", "")
    logger.info("YouTube notes: discover start id=%s url=%s", job_id, video_url)
    start = time.monotonic()
    try:
        video_id, links, error_summary, chapter_count = _discover_youtube_show_note_links(
            video_url
        )
        elapsed = time.monotonic() - start
        if video_id is None:
            queue.mark_done(job_id)
            logger.info(
                "YouTube notes: discover id=%s not-a-video elapsed=%.2fs",
                job_id, elapsed,
            )
            return
        if error_summary:
            queue.mark_failed(job_id, error_summary, retryable=True)
            logger.warning(
                "YouTube notes: discover id=%s unavailable elapsed=%.2fs reason=%s",
                job_id, elapsed, error_summary,
            )
            return

        if len(links) > MAX_YOUTUBE_SHOW_NOTE_LINKS:
            logger.warning(
                "YouTube notes: capped video_id=%s found=%d limit=%d",
                video_id, len(links), MAX_YOUTUBE_SHOW_NOTE_LINKS,
            )

        queued, duplicate = queue.enqueue_many(
            links[:MAX_YOUTUBE_SHOW_NOTE_LINKS],
            parent_video_id=video_id,
            kind=KIND_INGEST,
        )
        queue.mark_done(job_id)
        summary = (
            f"YouTube notes: video_id={video_id} "
            f"scanned={min(len(links), MAX_YOUTUBE_SHOW_NOTE_LINKS)} "
            f"found={len(links)} timestamps_ignored={chapter_count} "
            f"queued={queued} duplicate={duplicate} "
            f"queue_unfinished={queue.unfinished_count()}"
        )
        logger.info("YouTube notes: discovered %s", summary)
    except Exception as exc:  # noqa: BLE001 - a failed discovery must not kill the worker
        elapsed = time.monotonic() - start
        queue.mark_failed(job_id, str(exc), retryable=True)
        logger.exception(
            "YouTube notes: discover id=%s failed elapsed=%.2fs", job_id, elapsed
        )


def _process_ingest_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Record one discovered child URL, then record its terminal state."""
    job_id = job.get("id", "")
    url = job.get("url", "")
    logger.info("YouTube notes: job start id=%s url=%s", job_id, url)
    start = time.monotonic()
    try:
        result = process_one(
            url,
            force=False,
            _discover_youtube_links=False,
            _suppress_playlist_expansion=True,
        )
        elapsed = time.monotonic() - start
        if result.status == "error":
            queue.mark_failed(job_id, result.message, retryable=True)
            logger.warning(
                "YouTube notes: job id=%s url=%s status=error elapsed=%.2fs reason=%s",
                job_id, url, elapsed, result.message,
            )
        else:
            queue.mark_done(job_id)
            logger.info(
                "YouTube notes: job id=%s url=%s status=%s elapsed=%.2fs",
                job_id, url, result.status, elapsed,
            )
    except Exception as exc:  # noqa: BLE001 - a failed child must not kill the worker
        elapsed = time.monotonic() - start
        queue.mark_failed(job_id, str(exc), retryable=True)
        logger.exception(
            "YouTube notes: job id=%s url=%s failed elapsed=%.2fs", job_id, url, elapsed
        )


def _drain_show_notes_queue(queue: ShowNotesQueue) -> bool:
    """Claim and process at most one ready job. Returns True if any work was done."""
    job = queue.next_pending()
    if job is None:
        return False
    _process_queued_job(queue, job)
    return True


class _ShowNotesWorker:
    """Background daemon thread that drains the durable show-note queue."""

    def __init__(self, poll_interval: float = 0.5) -> None:
        self._poll_interval = poll_interval
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="ref-show-notes-worker", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            self._drain()
        finally:
            _worker_exited(self)

    def _drain(self) -> None:
        queue = _get_queue()
        try:
            queue.recover()
        except QueueCorruptError:
            logger.exception(
                "show-notes queue is corrupt; worker idle until an operator "
                "resolves it (never overwriting accepted jobs)"
            )
            while not self._stop.is_set():
                self._stop.wait(self._poll_interval)
            return
        while not self._stop.is_set():
            try:
                drained = _drain_show_notes_queue(queue)
            except QueueCorruptError:
                logger.error("show-notes queue became corrupt; pausing worker")
                self._stop.wait(self._poll_interval * 10)
                drained = False
            except Exception:  # noqa: BLE001 - keep the worker alive across bad jobs
                logger.exception("show-notes worker iteration failed")
                drained = False
            if not drained:
                self._stop.wait(self._poll_interval)

    def stop(self, timeout: float = 5.0) -> bool:
        """Signal stop and join; returns True only if the thread fully exited."""
        self._stop.set()
        self._thread.join(timeout)
        return not self._thread.is_alive()


def _worker_exited(worker: "_ShowNotesWorker") -> None:
    """Run on a worker thread's way out (see ``_ShowNotesWorker._run``).

    Hands off to a successor when a restart was requested while this worker was
    still draining; otherwise clears the singleton. This is the explicit
    lifecycle fence that prevents both (a) overlapping workers and (b) a silently
    idle queue after a timed-out stop followed by a lifespan restart.
    """
    global _worker, _restart_pending
    with _worker_lock:
        if _worker is not worker:
            # A newer worker already took over; this stale exit is a no-op.
            return
        if _restart_pending:
            _restart_pending = False
            successor = _ShowNotesWorker()
            _worker = successor
            successor.start()
        else:
            _worker = None


def start_show_notes_worker() -> None:
    """Start the background show-note worker (idempotent, no overlapping workers)."""
    global _worker, _restart_pending
    with _worker_lock:
        if _worker is not None and _worker.is_alive():
            # Previous worker is still draining (a prior stop timed out). Mark a
            # pending restart so it hands off to a successor on its way out
            # instead of leaving the queue idle.
            _restart_pending = True
            return
        _restart_pending = False
        _worker = _ShowNotesWorker()
        _worker.start()


def stop_show_notes_worker() -> None:
    """Stop the background show-note worker (idempotent).

    A shutdown request also cancels any pending restart, so a worker that is
    still draining on its way out does not hand off to a successor after the
    *latest* shutdown (only a still-active lifespan may have requested restart).
    Worker identity/generation fencing is handled by ``_worker_exited`` checking
    ``_worker is worker`` before acting.
    """
    global _worker, _restart_pending
    with _worker_lock:
        worker = _worker
        # A shutdown supersedes any earlier restart request.
        _restart_pending = False
    if worker is None:
        return
    # Join outside the lock so the exiting thread can acquire it for its
    # successor handoff (``_worker_exited``) without deadlocking.
    fully_stopped = worker.stop()
    with _worker_lock:
        # ``_worker_exited`` already ran on the worker thread if it exited, so
        # only clear when this worker is somehow still current and fully gone.
        if _worker is worker and fully_stopped:
            _worker = None
        # If the thread did not exit within the timeout (still in slow child
        # work), leave ``_worker`` set; ``_restart_pending`` is now False, so its
        # eventual exit clears the singleton instead of spawning a successor.


def process_many(inputs: List[str], force: bool = False) -> List[UrlResult]:
    """Process each input in order; ingest is serialized per URL via process_one."""
    return [process_one(item, force=force) for item in inputs]


_SEARCH_FIELDS = {
    "url": "url",
    "title": "title",
    "date": "date",
    "source": "source",
    "uploader": "uploader",
}


def search_archive(term: str, field: str = "all") -> List[SearchHit]:
    """Search references.md; ``field=all`` matches the CLI ``--search`` behavior."""
    term = term.strip()
    if not term:
        return []

    file_path = ref_cli.UNIFIED
    if field == "all":
        merged: dict[str, list[str]] = {}
        for search_field in _SEARCH_FIELDS:
            for line, hit_types in ref_cli.search_entries(
                term, search_field, file_path
            ).items():
                if line not in merged:
                    merged[line] = list(hit_types)
                else:
                    merged[line].extend(hit_types)
        return [
            SearchHit(line=line, hit_types=sorted(set(hit_types)))
            for line, hit_types in merged.items()
        ]

    search_field = _SEARCH_FIELDS.get(field)
    if search_field is None:
        raise ValueError(f"Unsupported search field: {field}")

    hits = ref_cli.search_entries(term, search_field, file_path)
    return [
        SearchHit(line=line, hit_types=sorted(set(hit_types)))
        for line, hit_types in hits.items()
    ]


def list_archive(
    *,
    limit: int | None = None,
    since: str | None = None,
) -> List[str]:
    """List URLs from references.md: last ``limit`` or within ``since`` duration."""
    from ref_api.listing import list_urls, parse_list_duration

    if (limit is None) == (since is None):
        raise ValueError("Provide exactly one of 'limit' or 'since'")

    since_delta = None
    if since is not None:
        since_delta = parse_list_duration(since)

    return list_urls(
        limit=limit,
        since=since_delta,
        file_path=ref_cli.UNIFIED,
    )


def create_references_backup(*, compress: bool = True) -> str:
    """Create a timestamped backup of references.md on the server."""
    from ref_cli.backup_util import backup_file

    with _write_lock:
        return backup_file(
            ref_cli.UNIFIED,
            compress=compress,
            style="timestamp_prefix",
        )


def _classify_transcript_stdout(stdout: str) -> str:
    text = (stdout or "").strip()
    lower = text.lower()
    if "has been updated" in lower:
        return "updated"
    if "stored failure reason" in lower:
        return "failure_recorded"
    if "no matching entry" in lower:
        return "not_found"
    if text.startswith("Error:") or lower.startswith("error:"):
        return "error"
    return "not_found" if not text else "error"


def update_transcript_for_url(video_url: str) -> TranscriptResult:
    """Run update_transcript on the server archive."""
    target = video_url.strip()
    if not target:
        return TranscriptResult(
            url=video_url,
            status="error",
            message="Empty URL",
            output="",
        )

    buf = io.StringIO()
    try:
        # ``ref_cli.update_transcript`` now manages its own archive lock (network
        # fetch outside the lock, read/decide/write commit inside it), so no
        # service-level lock is held here.
        with _capture_stdout(buf):
            ref_cli.update_transcript(target)
        output = buf.getvalue().strip()
        status = _classify_transcript_stdout(output)
        message = {
            "updated": "Transcript updated",
            "failure_recorded": "Failure recorded",
            "not_found": "No matching entry",
            "error": output.splitlines()[0] if output else "Transcript update failed",
        }.get(status, "")
        return TranscriptResult(
            url=target,
            status=status,
            message=message,
            output=output,
        )
    except Exception as exc:  # noqa: BLE001
        output = buf.getvalue().strip()
        logger.exception("Failed to update transcript for %s", target)
        return TranscriptResult(
            url=target,
            status="error",
            message=str(exc),
            output=output,
        )
