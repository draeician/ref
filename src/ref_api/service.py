"""Service layer: wrap ref_cli.cli.process_url for HTTP ingest."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

from ref_cli import cli as ref_cli
from ref_cli.capture import capture_scope, current_capture, sanitize_error_detail
from ref_cli.reddit import is_reddit_url
from ref_api.schemas import (
    ArchiveLookupResponse,
    DiscoveryResult,
    PrimaryCapture,
    SearchHit,
    TranscriptResult,
    UrlResult,
    UrlStatus,
)
from ref_api.show_notes_queue import (
    KIND_DISCOVER,
    KIND_INGEST,
    SOURCE_REDDIT,
    SOURCE_YOUTUBE,
    QueueCorruptError,
    ShowNotesQueue,
)
from ref_api.state_store import (
    IdempotencyAmbiguous,
    IdempotencyStore,
    StateStoreError,
    UrlIdentityStore,
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


def _classify_stdout(stdout: str) -> UrlStatus:  # pragma: no cover - legacy helper
    """Deprecated: retained only for external callers; never used for results.

    Primary status is recorded by :mod:`ref_cli.capture` at the archive write /
    exact existing-row check. This function must not be reintroduced on the
    ingest path.
    """
    text = (stdout or "").strip()
    lower = text.lower()
    if "already recorded" in lower:
        return "exists"
    if lower.startswith("error:") or "invalid url" in lower or "dead link" in lower:
        return "error"
    if text:
        return "added"
    return "error"


# Bound automatic fan-out per API request. Manual extraction has no such cap.
MAX_YOUTUBE_SHOW_NOTE_LINKS = 50
MAX_REDDIT_DISCOVERY_LINKS = 50

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

# Durable ref-api state (identity ledger + idempotency requests) beside the
# archive. Kept out of ``show_notes_queue`` so existing queue snapshots are not
# migrated or rewritten.
_STATE_DIRNAME = "ref_api_state"
_identity_store: Optional[UrlIdentityStore] = None
_identity_dir: Optional[str] = None
_identity_lock = threading.Lock()
_idempotency_store: Optional[IdempotencyStore] = None
_idempotency_dir: Optional[str] = None
_idempotency_lock = threading.Lock()


def _state_directory() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(ref_cli.UNIFIED)), _STATE_DIRNAME
    )


def _get_identity_store() -> UrlIdentityStore:
    global _identity_store, _identity_dir
    current = _state_directory()
    with _identity_lock:
        if _identity_store is None or _identity_dir != current:
            _identity_store = UrlIdentityStore(current)
            _identity_dir = current
        return _identity_store


def _get_idempotency_store() -> IdempotencyStore:
    global _idempotency_store, _idempotency_dir
    current = _state_directory()
    with _idempotency_lock:
        if _idempotency_store is None or _idempotency_dir != current:
            _idempotency_store = IdempotencyStore(current)
            _idempotency_dir = current
        return _idempotency_store


def _queue_directory() -> str:
    """Absolute path of the show-note queue directory beside references.md."""
    return os.path.join(
        os.path.dirname(os.path.abspath(ref_cli.UNIFIED)), _QUEUE_DIRNAME
    )


def _archive_fingerprint() -> str:
    """Content fingerprint used to detect whether an interrupted attempt wrote.

    The read is taken under the shared archive lock so it cannot straddle a
    partial append/rewrite.  A missing archive is represented explicitly; an
    unreadable archive raises :class:`StateStoreError` because a forced retry
    cannot then be proven safe.
    """
    try:
        with ref_cli._archive_lock:
            with open(ref_cli.UNIFIED, "rb") as handle:
                data = handle.read()
    except FileNotFoundError:
        return "missing"
    except OSError as exc:  # noqa: BLE001 - no proof means no forced replay
        raise StateStoreError(f"archive fingerprint unavailable: {exc}") from exc
    return "sha256:" + hashlib.sha256(data).hexdigest()


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


def rollback_safety() -> Dict[str, Any]:
    """Read-only downgrade check for Reddit discovery metadata.

    An older ref-api reconstructs jobs without the additive ``source`` field.
    A pending/running Reddit ``discover`` job is then consumed as a no-op
    YouTube job, and any older snapshot write strips ``source`` from every job,
    including terminal ``failed`` ones.  Downgrade is therefore blocked while
    any Reddit discovery job is pending, running or failed.  A ``done`` job has
    no outstanding work and does not block.  A corrupt/unreadable queue blocks.

    This function is strictly read-only.  Run it offline after the service has
    stopped and no further submissions can reach the queue; the persisted file
    is then the final state the older build would read.
    """
    queue = _get_queue()
    try:
        blockers = queue.rollback_blockers()
    except QueueCorruptError as exc:
        detail = sanitize_error_detail(f"queue corrupt: {exc}")
        return {
            "safe": False,
            "blocked": True,
            "corrupt": True,
            "blockers": [],
            "failed_preserved": 0,
            "reason": detail,
        }

    summaries = [
        {
            "job_id": job.get("id", ""),
            "url": sanitize_error_detail(job.get("url", "")),
            "status": job.get("status", ""),
            "attempts": int(job.get("attempts", 0)),
            "parent_video_id": job.get("parent_video_id", ""),
        }
        for job in blockers
    ]
    failed_blocking = sum(1 for job in blockers if job.get("status") == "failed")
    if summaries:
        reason = (
            "Downgrade blocked: Reddit discovery jobs exist that an older "
            "ref-api cannot preserve. Pending/running jobs would be consumed as "
            "no-op YouTube jobs, and a terminal failed job would lose its "
            "'source' metadata on the older build's next snapshot write. Drain "
            "or resolve these jobs on the current build before downgrading."
        )
    else:
        reason = (
            "No pending/running/failed Reddit discovery jobs; downgrade is safe."
        )
    return {
        "safe": not summaries,
        "blocked": bool(summaries),
        "corrupt": False,
        "blockers": summaries,
        "failed_preserved": failed_blocking,
        "reason": reason,
    }


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
        detail = sanitize_error_detail(exc)
        logger.warning(
            "YouTube notes: unavailable video_id=%s reason=%s", video_id, detail
        )
        return video_id, [], f"YouTube notes: unavailable for {video_id} ({detail})", 0

    logger.info(
        "YouTube notes: metadata video_id=%s source=%s description_chars=%d "
        "timestamps_ignored=%d outbound_links=%d",
        video_id, card.get("source") or "cache", len(description),
        chapter_count, len(links),
    )
    return video_id, links, "", chapter_count


def _discovery_line(
    source: str,
    *,
    status: str,
    job_id: Optional[str] = None,
    video_id: str = "",
    detail: str = "",
) -> str:
    """Human-readable one-line discovery summary (kept for CLI compatibility)."""
    label = "Reddit" if source == SOURCE_REDDIT else "YouTube notes"
    if status == "queued":
        if video_id:
            return f"{label}: discovery queued video_id={video_id} job={job_id}"
        return f"{label}: discovery queued job={job_id}"
    if status == "already_queued":
        return f"{label}: discovery already queued job={job_id}" if job_id else f"{label}: discovery already queued"
    if status == "already_completed":
        return f"{label}: discovery already completed"
    return f"{label}: discovery not queued ({detail or 'unknown error'})"


def _discovery_source(
    stored_url: str,
    *,
    allow_youtube: bool,
    allow_reddit: bool,
) -> tuple[str, str]:
    """Return ``(source, video_id)`` for discovery, or ``("", "")``.

    Kept separate so a post-capture formatting/import failure cannot turn a
    confirmed primary result into an error, and so the caller can report a
    failed discovery without guessing whether discovery applied.
    """
    if allow_reddit and is_reddit_url(stored_url):
        return SOURCE_REDDIT, ""
    if allow_youtube:
        from ref_cli.youtube_extract import youtube_video_id

        video_id = youtube_video_id(stored_url) or ""
        if video_id:
            return SOURCE_YOUTUBE, video_id
    return "", ""


def _enqueue_capture_discovery(
    stored_url: str,
    *,
    allow_youtube: bool,
    allow_reddit: bool,
) -> Optional[DiscoveryResult]:
    """Durably enqueue discovery for a confirmed primary URL.

    Returns ``None`` when discovery does not apply.  A ``queued`` status is
    returned only after the queue snapshot was written; any enqueue failure is
    reported as ``failed`` and never as queued.
    """
    source, video_id = _discovery_source(
        stored_url, allow_youtube=allow_youtube, allow_reddit=allow_reddit
    )
    if not source:
        return None

    safe_url = sanitize_error_detail(stored_url)
    try:
        queue = _get_queue()
        job_id = queue.enqueue_discovery(stored_url, video_id, source=source)
    except QueueCorruptError as exc:
        detail = sanitize_error_detail(f"queue corrupt: {exc}")
        logger.error(
            "Discovery: queue corrupt, not queued source=%s url=%s reason=%s",
            source, safe_url, detail,
        )
        return DiscoveryResult(status="failed", detail=detail)
    except Exception as exc:  # noqa: BLE001 - durable enqueue must fail closed
        detail = sanitize_error_detail(
            f"{type(exc).__name__}: {exc}"
        )
        logger.error(
            "Discovery: enqueue failed source=%s url=%s reason=%s",
            source, safe_url, detail,
        )
        return DiscoveryResult(status="failed", detail=detail)

    if job_id:
        if source == SOURCE_YOUTUBE and video_id:
            logger.info(
                "YouTube notes: discovery queued video_id=%s job=%s",
                video_id, job_id,
            )
        else:
            logger.info(
                "Reddit discovery: queued url=%s job=%s", safe_url, job_id
            )
        return DiscoveryResult(status="queued", job_id=job_id)

    # Dedup: report the existing durable job/state, never a fabricated id.
    try:
        existing = queue.find_job(stored_url, kind=KIND_DISCOVER)
    except Exception as exc:  # noqa: BLE001
        detail = sanitize_error_detail(f"queue lookup failed: {exc}")
        logger.error(
            "Discovery: dedup lookup failed source=%s url=%s reason=%s",
            source, safe_url, detail,
        )
        return DiscoveryResult(status="failed", detail=detail)
    if existing is None:
        logger.error(
            "Discovery: enqueue returned no job and none found source=%s url=%s",
            source, safe_url,
        )
        return DiscoveryResult(
            status="failed", detail="enqueue returned no job and no existing job was found"
        )
    if existing.get("status") == "done":
        return DiscoveryResult(
            status="already_completed", job_id=existing.get("id")
        )
    if existing.get("status") == "failed":
        return DiscoveryResult(
            status="failed",
            job_id=existing.get("id"),
            detail=sanitize_error_detail(existing.get("last_error") or "previous discovery failed"),
        )
    return DiscoveryResult(status="already_queued", job_id=existing.get("id"))


def _enqueue_youtube_discovery(video_url: str, video_id: str) -> str:
    """Backward-compatible YouTube discovery helper used by older callers/tests."""
    result = _enqueue_capture_discovery(
        video_url, allow_youtube=True, allow_reddit=False
    )
    if result is None:
        return ""
    return _discovery_line(
        SOURCE_YOUTUBE,
        status=result.status,
        job_id=result.job_id,
        video_id=video_id,
        detail=result.detail,
    )


def _exact_archive_match(url: str) -> bool:
    """True when an exact parsed archive row stores ``url`` (never substring)."""
    from ref_cli.references_format import exact_url_rows

    try:
        return bool(exact_url_rows(ref_cli.UNIFIED, url))
    except FileNotFoundError:
        return False


def _remember_identity(original: str, target: str, stored_url: str) -> bool:
    """Persist original/target -> stored identity; never fail the capture."""
    try:
        store = _get_identity_store()
        store.record(original, stored_url)
        if target and target != original:
            store.record(target, stored_url)
        return True
    except Exception as exc:  # noqa: BLE001 - identity is auxiliary, never fail capture
        logger.warning(
            "Identity ledger: could not record url=%s stored=%s (%s: %s)",
            sanitize_error_detail(original), sanitize_error_detail(stored_url),
            type(exc).__name__, sanitize_error_detail(exc),
        )
        return False


def _capture_status(
    target: str,
) -> tuple[Optional[Any], str, str]:
    """Return ``(capture_result, status, detail)`` for the current thread."""
    capture, capture_error = current_capture()
    if capture is not None:
        return capture, capture.status, ""
    if capture_error:
        return None, "error", capture_error
    return None, "error", "Primary capture was not confirmed"


def _build_primary_result(
    *,
    original: str,
    target: str,
    capture: Any,
    output: str,
    discover_youtube: bool,
    discover_reddit: bool,
    auxiliary_error: str = "",
) -> UrlResult:
    """Build a result from a recorded primary capture.

    The primary archive row is already committed. Identity bookkeeping and
    discovery enqueue (and any playlist child work that may have run before an
    exception) are auxiliary: their failure is reported, but it never changes the
    primary status or removes ``primary`` from the response.
    """
    stored_url = capture.url
    if not _exact_archive_match(stored_url):
        detail = (
            "Primary capture reported "
            f"{capture.status!r} for {stored_url} but no exact archive row was found"
        )
        safe_detail = sanitize_error_detail(detail)
        logger.error(
            "Capture verification failed url=%s stored=%s status=%s",
            sanitize_error_detail(target),
            sanitize_error_detail(stored_url),
            capture.status,
        )
        return UrlResult(
            input=original,
            url=target,
            status="error",
            message=safe_detail,
            output=output,
            error=safe_detail,
        )

    identity_recorded = _remember_identity(original, target, stored_url)
    primary = PrimaryCapture(
        status=capture.status,
        canonical_url=stored_url,
        archive_confirmed=True,
        source=capture.source,
        identity_recorded=identity_recorded,
    )

    discovery: Optional[DiscoveryResult] = None
    if auxiliary_error:
        output = (
            f"{output}\nPost-capture work failed: {auxiliary_error}"
            if output
            else f"Post-capture work failed: {auxiliary_error}"
        )
    else:
        try:
            source, video_id = _discovery_source(
                stored_url,
                allow_youtube=discover_youtube,
                allow_reddit=discover_reddit,
            )
            discovery = _enqueue_capture_discovery(
                stored_url,
                allow_youtube=discover_youtube,
                allow_reddit=discover_reddit,
            )
            if discovery is not None:
                summary = _discovery_line(
                    source or SOURCE_YOUTUBE,
                    status=discovery.status,
                    job_id=discovery.job_id,
                    video_id=video_id,
                    detail=discovery.detail,
                )
                output = f"{output}\n{summary}" if output else summary
        except Exception as exc:  # noqa: BLE001 - primary is already committed
            detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
            discovery = DiscoveryResult(status="failed", detail=detail)
            logger.error(
                "Post-capture discovery failed url=%s reason=%s",
                sanitize_error_detail(stored_url),
                detail,
            )

    message = {
        "added": "Recorded",
        "exists": "Already recorded",
    }.get(capture.status, "")
    return UrlResult(
        input=original,
        url=stored_url,
        status=capture.status,
        message=message,
        output=output,
        primary=primary,
        discovery=discovery,
    )


def process_one(
    raw_input: str,
    force: bool = False,
    *,
    _discover_youtube_links: bool = True,
    _discover_reddit_links: bool = True,
    _suppress_playlist_expansion: bool = False,
) -> UrlResult:
    """
    Apply skip patterns, convert YouTube video IDs, then call process_url.

    Archive writes are serialized inside ``ref_cli`` (its ``_archive_lock``), not
    by a lock held across the whole ``process_url`` call, so slow provider/network
    work for one URL does not block another caller's archive write. The primary
    status comes from the capture recorder (archive write / exact existing-row
    check), never from stdout. Parent YouTube/Reddit captures only *enqueue* a
    durable discovery job; provider work runs on the worker.

    ``_suppress_playlist_expansion`` is set only by the background worker so a
    discovered playlist link is recorded without full playlist traversal.
    ``_discover_reddit_links=False`` is used on the worker to prevent recursive
    Reddit -> child -> Reddit expansion.
    """
    original = raw_input.strip()
    if not original:
        return UrlResult(
            input=raw_input,
            url=raw_input,
            status="error",
            message="Empty URL",
            output="",
            error="Empty URL",
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
            with capture_scope():
                if _suppress_playlist_expansion and _is_youtube_playlist_url(target):
                    ref_cli.record_youtube_playlist_link(target, force)
                else:
                    ref_cli.process_url(
                        target,
                        force,
                        # Reddit discovery is always asynchronous via the queue
                        # on the API path; never do it synchronously here.
                        discover_reddit_links=False,
                    )
        output = buf.getvalue().strip()
        capture, status, detail = _capture_status(target)

        if status not in {"added", "exists"} or capture is None:
            message = sanitize_error_detail(
                detail or (output.splitlines()[0] if output else "Processing failed")
            )
            return UrlResult(
                input=original,
                url=target,
                status="error",
                message=message,
                output=output,
                error=message,
            )

        return _build_primary_result(
            original=original,
            target=target,
            capture=capture,
            output=output,
            discover_youtube=_discover_youtube_links,
            discover_reddit=_discover_reddit_links,
        )
    except Exception as exc:  # noqa: BLE001 - primary may already be committed
        output = buf.getvalue().strip()
        reason = sanitize_error_detail(f"{type(exc).__name__}: {exc}")

        # ``process_url`` may commit the primary archive row and then fail in
        # auxiliary work (for example a playlist child or formatting). The
        # recorder keeps the confirmed primary after the scope unwinds, so a
        # committed capture must never be downgraded to an error.
        capture, status, _detail = _capture_status(target)
        if capture is not None and status in {"added", "exists"}:
            try:
                recovered = _build_primary_result(
                    original=original,
                    target=target,
                    capture=capture,
                    output=output,
                    discover_youtube=_discover_youtube_links,
                    discover_reddit=_discover_reddit_links,
                    auxiliary_error=reason,
                )
            except Exception as verify_exc:  # noqa: BLE001 - fall back to error
                reason = sanitize_error_detail(
                    f"{reason}; recovery verification failed: "
                    f"{type(verify_exc).__name__}: {verify_exc}"
                )
            else:
                logger.warning(
                    "Post-capture work failed but primary is committed url=%s "
                    "status=%s reason=%s",
                    sanitize_error_detail(target),
                    status,
                    reason,
                )
                return recovered

        logger.error(
            "Failed to process URL url=%s exception=%s reason=%s",
            sanitize_error_detail(target), type(exc).__name__, reason,
        )
        return UrlResult(
            input=original,
            url=target,
            status="error",
            message=reason,
            output=output,
            error=reason,
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
    """Dispatch a durable discovery job by source (default: YouTube)."""
    if job.get("source") == SOURCE_REDDIT:
        _process_reddit_discovery_job(queue, job)
    else:
        _process_youtube_discovery_job(queue, job)


def _process_reddit_discovery_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Discover Reddit outbound links on the worker, then enqueue child ingests."""
    from ref_cli.reddit import discover_outbound_urls_detailed

    job_id = job.get("id", "")
    url = job.get("url", "")
    safe_url = sanitize_error_detail(url)
    logger.info("Reddit discovery: start id=%s url=%s", job_id, safe_url)
    start = time.monotonic()
    try:
        result = discover_outbound_urls_detailed(url)
        elapsed = time.monotonic() - start
        if result.status in ("unavailable", "error"):
            detail = sanitize_error_detail(
                result.detail or f"Reddit provider {result.status}"
            )
            queue.mark_failed(job_id, detail, retryable=True)
            logger.warning(
                "Reddit discovery: id=%s unavailable elapsed=%.2fs status=%s reason=%s",
                job_id, elapsed, result.status, detail,
            )
            return
        if result.status == "not_found":
            # An archive miss is not an error and is not retryable here.
            queue.mark_done(job_id)
            logger.info(
                "Reddit discovery: id=%s not-found elapsed=%.2fs", job_id, elapsed
            )
            return

        links = result.urls
        if len(links) > MAX_REDDIT_DISCOVERY_LINKS:
            logger.warning(
                "Reddit discovery: capped url=%s found=%d limit=%d",
                safe_url, len(links), MAX_REDDIT_DISCOVERY_LINKS,
            )
        queued, duplicate = queue.enqueue_many(
            links[:MAX_REDDIT_DISCOVERY_LINKS],
            kind=KIND_INGEST,
            source=SOURCE_REDDIT,
        )
        queue.mark_done(job_id)
        logger.info(
            "Reddit discovery: discovered id=%s found=%d scanned=%d queued=%d "
            "duplicate=%d queue_unfinished=%d",
            job_id, len(links), min(len(links), MAX_REDDIT_DISCOVERY_LINKS),
            queued, duplicate, queue.unfinished_count(),
        )
    except Exception as exc:  # noqa: BLE001 - a failed discovery must not kill the worker
        elapsed = time.monotonic() - start
        detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        queue.mark_failed(job_id, detail, retryable=True)
        logger.error(
            "Reddit discovery: id=%s failed elapsed=%.2fs url=%s reason=%s",
            job_id, elapsed, safe_url, detail,
        )


def _process_youtube_discovery_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Fetch a video's show notes (network, no lock) and enqueue its child links."""
    job_id = job.get("id", "")
    video_url = job.get("url", "")
    safe_url = sanitize_error_detail(video_url)
    logger.info("YouTube notes: discover start id=%s url=%s", job_id, safe_url)
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
        detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        queue.mark_failed(job_id, detail, retryable=True)
        logger.error(
            "YouTube notes: discover id=%s failed elapsed=%.2fs reason=%s",
            job_id, elapsed, detail,
        )


def _process_ingest_job(queue: ShowNotesQueue, job: Dict[str, Any]) -> None:
    """Record one discovered child URL, then record its terminal state."""
    job_id = job.get("id", "")
    url = job.get("url", "")
    safe_url = sanitize_error_detail(url)
    logger.info("YouTube notes: job start id=%s url=%s", job_id, safe_url)
    start = time.monotonic()
    try:
        result = process_one(
            url,
            force=False,
            _discover_youtube_links=False,
            _discover_reddit_links=False,
            _suppress_playlist_expansion=True,
        )
        elapsed = time.monotonic() - start
        if result.status == "error":
            detail = sanitize_error_detail(result.error or result.message)
            queue.mark_failed(job_id, detail, retryable=True)
            logger.warning(
                "show-notes: job id=%s url=%s status=error elapsed=%.2fs reason=%s",
                job_id, safe_url, elapsed, detail,
            )
        else:
            queue.mark_done(job_id)
            logger.info(
                "show-notes: job id=%s url=%s status=%s elapsed=%.2fs",
                job_id, safe_url, result.status, elapsed,
            )
    except Exception as exc:  # noqa: BLE001 - a failed child must not kill the worker
        elapsed = time.monotonic() - start
        detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        queue.mark_failed(job_id, detail, retryable=True)
        logger.error(
            "show-notes: job id=%s url=%s failed elapsed=%.2fs reason=%s",
            job_id, safe_url, elapsed, detail,
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
        except QueueCorruptError as exc:
            logger.error(
                "show-notes queue is corrupt; worker idle until an operator "
                "resolves it (never overwriting accepted jobs) reason=%s",
                sanitize_error_detail(exc),
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
            except Exception as exc:  # noqa: BLE001 - keep the worker alive across bad jobs
                logger.error(
                    "show-notes worker iteration failed reason=%s",
                    sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
                )
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


# ---------------------------------------------------------------------------
# Automatic transcript reconciliation
# ---------------------------------------------------------------------------
#
# The durable local-transcribe queue completes work asynchronously. A periodic
# pass replaces queued placeholders in references.md with the validated shared
# transcript path. The core logic lives in ``ref_cli.transcript_reconcile`` so it
# can be tested without the API. This worker only schedules it.

_reconcile_worker: Optional["_TranscriptReconcileWorker"] = None
_reconcile_worker_lock = threading.Lock()


def _reconcile_config() -> Dict[str, Any]:
    """Load transcript-reconciliation config without failing the service."""
    config_file = getattr(ref_cli, "CONFIG_FILE", "")
    if not config_file or not os.path.exists(config_file):
        return {}
    try:
        config = ref_cli.load_config()
        return config if isinstance(config, dict) else {}
    except Exception:  # noqa: BLE001 - config is advisory only
        logger.warning(
            "Transcript reconciliation: unable to load config", exc_info=True
        )
        return {}


def _run_transcript_reconciliation_once(
    config: Optional[Dict[str, Any]] = None,
) -> Any:
    """Run one reconciliation pass against the service archive."""
    from ref_cli.transcript_reconcile import reconcile_transcripts

    if config is None:
        config = _reconcile_config()

    result = reconcile_transcripts(
        archive_path=ref_cli.UNIFIED,
        config=config,
    )
    if result.updated:
        logger.info("Transcript reconciliation: %s", result.summary())
    elif result.candidates or result.errors:
        logger.info("Transcript reconciliation: %s", result.summary())
    else:
        logger.debug("Transcript reconciliation: no queued placeholders")
    return result


class _TranscriptReconcileWorker:
    """Background daemon thread that runs reconciliation on an interval."""

    def __init__(
        self,
        interval_seconds: float,
        reconcile_once=None,
    ) -> None:
        self._interval = max(float(interval_seconds), 0.001)
        self._reconcile_once = reconcile_once or _run_transcript_reconciliation_once
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="ref-transcript-reconciler", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    self._reconcile_once()
                except Exception as exc:  # noqa: BLE001 - keep the reconciler alive
                    logger.error(
                        "Transcript reconciliation iteration failed reason=%s",
                        sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
                    )
                self._stop.wait(self._interval)
        finally:
            _reconcile_worker_exited(self)

    def stop(self, timeout: float = 5.0) -> bool:
        """Signal stop and join; True only if the thread fully exited."""
        self._stop.set()
        self._thread.join(timeout)
        return not self._thread.is_alive()


def _reconcile_worker_exited(worker: "_TranscriptReconcileWorker") -> None:
    global _reconcile_worker
    with _reconcile_worker_lock:
        if _reconcile_worker is worker:
            _reconcile_worker = None


def start_transcript_reconciler(
    *,
    interval_seconds: Optional[float] = None,
    reconcile_once=None,
) -> bool:
    """Start the reconciler (idempotent). Returns False when disabled."""
    from ref_cli.transcript_reconcile import (
        resolve_enabled,
        resolve_interval_seconds,
    )

    global _reconcile_worker
    config = _reconcile_config()
    if not resolve_enabled(config):
        logger.info("Transcript reconciliation disabled")
        return False

    interval = (
        interval_seconds
        if interval_seconds is not None
        else resolve_interval_seconds(config)
    )
    with _reconcile_worker_lock:
        if _reconcile_worker is not None and _reconcile_worker.is_alive():
            return True
        _reconcile_worker = _TranscriptReconcileWorker(
            interval, reconcile_once=reconcile_once
        )
        _reconcile_worker.start()
        logger.info(
            "Transcript reconciliation started (interval=%ss)", interval
        )
        return True


def stop_transcript_reconciler(*, timeout: float = 5.0) -> None:
    """Stop the reconciler cleanly (idempotent)."""
    global _reconcile_worker
    with _reconcile_worker_lock:
        worker = _reconcile_worker
    if worker is None:
        return
    fully_stopped = worker.stop(timeout=timeout)
    with _reconcile_worker_lock:
        if _reconcile_worker is worker and fully_stopped:
            _reconcile_worker = None
    logger.info("Transcript reconciliation stopped")


def process_many(inputs: List[str], force: bool = False) -> List[UrlResult]:
    """Process each input in order; ingest is serialized per URL via process_one."""
    return [process_one(item, force=force) for item in inputs]


def request_hash(inputs: List[str], force: bool) -> str:
    """Stable hash of the effective request payload (ordered inputs + force)."""
    payload = json.dumps(
        {"inputs": list(inputs), "force": bool(force)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reconcile_documented_discovery(result: UrlResult) -> UrlResult:
    """Ensure a confirmed prior result still has its discovery job enqueued.

    A reconciliation failure must not turn an authoritative primary success into
    an error; it is reported as a failed discovery on the preserved result.
    """
    primary = result.primary
    if primary is None or not primary.archive_confirmed:
        return result
    if result.discovery is not None and result.discovery.status in (
        "queued",
        "already_queued",
        "already_completed",
    ):
        return result
    try:
        if not _exact_archive_match(primary.canonical_url):
            return result
        discovery = _enqueue_capture_discovery(
            primary.canonical_url, allow_youtube=True, allow_reddit=True
        )
        if discovery is None:
            return result
        return result.model_copy(update={"discovery": discovery})
    except Exception as exc:  # noqa: BLE001 - primary is already authoritative
        detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        logger.error(
            "Discovery reconciliation failed url=%s reason=%s",
            sanitize_error_detail(primary.canonical_url),
            detail,
        )
        return result.model_copy(
            update={"discovery": DiscoveryResult(status="failed", detail=detail)}
        )


def _parse_stored_results(raw_results: List[Any], inputs: List[str]) -> List[Optional[UrlResult]]:
    """Parse stored results positionally, accepting only well-formed entries."""
    parsed: List[Optional[UrlResult]] = [None] * len(inputs)
    for index, raw in enumerate(raw_results[: len(inputs)]):
        if not isinstance(raw, dict):
            continue
        try:
            result = UrlResult(**raw)
        except Exception:  # noqa: BLE001 - malformed state is not trusted
            continue
        if result.input != inputs[index]:
            # Do not attach a result to a different input position.
            continue
        parsed[index] = result
    return parsed


def _serialize_results(
    results: List[Optional[UrlResult]],
) -> List[Optional[Dict[str, Any]]]:
    """Serialize results positionally, preserving ``None`` for unprocessed inputs."""
    return [
        result.model_dump() if result is not None else None for result in results
    ]


def _ambiguous_forced_message(key: str) -> str:
    return (
        f"Idempotency-Key {key!r} is ambiguous: an earlier forced request may "
        "already have modified the archive, and no durable result proves whether "
        "it committed. Refusing to repeat the forced write. Inspect "
        f"GET /requests/{key} and use a new key only if another forced capture "
        "is intentionally required."
    )


def process_many_idempotent(
    inputs: List[str],
    *,
    idempotency_key: str,
    force: bool = False,
) -> tuple[List[UrlResult], bool]:
    """Process inputs under a durable idempotency key.

    Returns ``(results, replayed)``. Same key + same payload is replayed from
    durable state after completion and reconciled (without re-running confirmed
    work) after an interruption. A different payload raises
    :class:`IdempotencyConflict`.

    For a **forced** request, each input's pre-work archive fingerprint is
    persisted before processing. If an interrupted attempt left no result and
    the archive content has changed, the request is marked ``ambiguous`` and
    :class:`IdempotencyAmbiguous` is raised instead of repeating a write that may
    already have committed. A non-forced retry remains safe because re-processing
    is idempotent (exact existing-row checks and queue dedup).

    This is **at-least-once with idempotent effects**, not exactly-once. See
    README for retention/concurrency and ambiguous-recovery semantics.
    """
    store = _get_idempotency_store()
    digest = request_hash(inputs, force)
    with store.key_lock(idempotency_key):
        entry = store.begin(
            idempotency_key,
            request_hash=digest,
            inputs=inputs,
            force=force,
        )
        was_completed = entry.get("state") == "completed"
        stored = _parse_stored_results(list(entry.get("results", [])), inputs)
        attempts: List[Optional[Dict[str, Any]]] = list(
            entry.get("attempts") or [None] * len(inputs)
        )
        if len(attempts) != len(inputs):
            attempts = [None] * len(inputs)

        if was_completed and all(result is not None for result in stored):
            return [result for result in stored if result is not None], True

        if was_completed and force:
            # A completed forced request with a missing/malformed result is not
            # safe to re-execute.
            message = _ambiguous_forced_message(idempotency_key)
            store.mark_ambiguous(
                idempotency_key,
                results=_serialize_results(stored),
                attempts=attempts,
                error=message,
            )
            raise IdempotencyAmbiguous(message)

        results: List[Optional[UrlResult]] = list(stored)
        for index, item in enumerate(inputs):
            prior = results[index]
            if prior is not None and prior.primary and prior.primary.archive_confirmed:
                attempts[index] = None
                results[index] = _reconcile_documented_discovery(prior)
                store.update(
                    idempotency_key,
                    results=_serialize_results(results),
                    attempts=attempts,
                )
                continue

            attempt = attempts[index]
            if attempt is not None and force:
                current_fingerprint = _archive_fingerprint()
                if current_fingerprint != attempt.get("fingerprint"):
                    message = _ambiguous_forced_message(idempotency_key)
                    store.mark_ambiguous(
                        idempotency_key,
                        results=_serialize_results(results),
                        attempts=attempts,
                        error=message,
                    )
                    raise IdempotencyAmbiguous(message)

            # Persist the pre-work fingerprint *before* any archive mutation so
            # a crash can be classified as safe-to-retry or ambiguous.
            fingerprint = _archive_fingerprint()
            attempts[index] = {
                "fingerprint": fingerprint,
                "started_at": time.time(),
            }
            store.update(
                idempotency_key,
                results=_serialize_results(results),
                attempts=attempts,
            )

            results[index] = process_one(item, force=force)
            attempts[index] = None
            store.update(
                idempotency_key,
                results=_serialize_results(results),
                attempts=attempts,
            )

        store.update(
            idempotency_key,
            results=_serialize_results(results),
            attempts=attempts,
            completed=True,
        )
        return [result for result in results if result is not None], was_completed


def get_idempotency_request(key: str) -> Optional[Dict[str, Any]]:
    """Read-only lookup of a stored idempotency request."""
    try:
        return _get_idempotency_store().get(key)
    except StateStoreError:
        raise


def lookup_url(url_value: str) -> ArchiveLookupResponse:
    """Read-only exact/canonical archive lookup.

    No normalization, substring search, ingestion, enqueue or archive mutation
    happens here. A ``canonical`` match requires a persisted identity record from
    an earlier confirmed capture.
    """
    value = (url_value or "").strip()
    if not value:
        return ArchiveLookupResponse(
            input=url_value,
            status="unknown",
            identity="invalid",
            message="Empty URL",
            error="Provide a non-empty 'url'",
        )

    from urllib.parse import urlsplit

    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("absolute http(s) URL required")
        if parsed.scheme.lower() not in ("http", "https"):
            raise ValueError("absolute http(s) URL required")
    except ValueError:
        return ArchiveLookupResponse(
            input=value,
            status="unknown",
            identity="invalid",
            message="URL is not an absolute http(s) URL",
            error="Provide an absolute http:// or https:// URL",
        )

    if not os.path.isfile(ref_cli.UNIFIED):
        return ArchiveLookupResponse(
            input=value,
            status="error",
            identity="none",
            message="Archive is unavailable",
            error="references.md was not found on the server",
        )

    try:
        if _exact_archive_match(value):
            return ArchiveLookupResponse(
                input=value,
                status="exists",
                archive_confirmed=True,
                exact_match=True,
                deletion_safe=True,
                canonical_url=value,
                stored_url=value,
                identity="exact",
                message="Exact archive row found",
            )
    except Exception as exc:  # noqa: BLE001 - report lookup failure explicitly
        logger.error(
            "Archive lookup failed url=%s reason=%s",
            sanitize_error_detail(value),
            sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
        )
        return ArchiveLookupResponse(
            input=value,
            status="error",
            identity="none",
            message="Archive lookup failed",
            error=sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
        )

    try:
        mapped = _get_identity_store().lookup(value)
    except StateStoreError as exc:
        logger.error(
            "Identity lookup failed url=%s (%s)",
            sanitize_error_detail(value),
            type(exc).__name__,
        )
        return ArchiveLookupResponse(
            input=value,
            status="error",
            identity="none",
            message="Identity ledger is unavailable",
            error=sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Identity lookup failed url=%s reason=%s",
            sanitize_error_detail(value),
            sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
        )
        return ArchiveLookupResponse(
            input=value,
            status="error",
            identity="none",
            message="Identity lookup failed",
            error=sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
        )

    if mapped:
        try:
            if _exact_archive_match(mapped):
                return ArchiveLookupResponse(
                    input=value,
                    status="canonical",
                    archive_confirmed=True,
                    exact_match=False,
                    deletion_safe=True,
                    canonical_url=mapped,
                    stored_url=mapped,
                    identity="ledger",
                    message="Authoritatively resolved canonical archive match",
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Canonical archive lookup failed url=%s reason=%s",
                sanitize_error_detail(value),
                sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
            )
            return ArchiveLookupResponse(
                input=value,
                status="error",
                identity="ledger",
                canonical_url=mapped,
                message="Archive lookup failed",
                error=sanitize_error_detail(f"{type(exc).__name__}: {exc}"),
            )
        return ArchiveLookupResponse(
            input=value,
            status="unknown",
            identity="unresolved",
            canonical_url=mapped,
            message="A recorded identity exists but its archive row is missing",
            error=(
                "Recorded canonical URL is not present in the archive: "
                f"{sanitize_error_detail(mapped)}"
            ),
        )

    return ArchiveLookupResponse(
        input=value,
        status="absent",
        identity="none",
        message=(
            "No exact or recorded canonical archive match; this is not proof "
            "that the reference was never captured"
        ),
    )


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


def list_urls_for_domain(domain: str) -> List[str]:
    """URLs on the server archive whose host is ``domain`` or a subdomain.

    Read-only listing (newest first). Raises ``ValueError`` for an invalid domain.
    """
    from ref_api.listing import list_urls_by_domain

    return list_urls_by_domain(domain=domain, file_path=ref_cli.UNIFIED)


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
        detail = sanitize_error_detail(f"{type(exc).__name__}: {exc}")
        logger.error(
            "Failed to update transcript url=%s reason=%s",
            sanitize_error_detail(target),
            detail,
        )
        return TranscriptResult(
            url=target,
            status="error",
            message=detail,
            output=output,
        )
