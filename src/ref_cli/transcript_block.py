"""Persisted YouTube transcript IP-block cooldown and recovery-probe lease.

When YouTube blocks transcript requests from this host's public IP, ``ref`` stops
calling ``youtube-transcript-api`` for a configurable window so an IP-ban request
storm cannot keep compounding already-slow synchronous ingests with per-video
blocked fetches and repeated warnings.

The expiry marker lives in the archive's transcripts state directory (outside the
repository) so separate CLI and API processes sharing the archive all honour the
same cooldown and it survives service restarts.

Interface (used by ``ref_cli.cli``):

* ``is_blocked(transcripts_dir, now=None)`` -- should provider transcript calls be
  suppressed right now by an active cooldown?
* ``begin_probe(transcripts_dir, now=None)`` -> :class:`ProbeDecision`. While a
  cooldown is active (or another process owns the single recovery probe, or the
  post-failure probe backoff is still pending) it returns ``allowed=False`` so the
  caller skips the remote call and routes to the queue-first/pending-file
  fallback. After cooldown expiry exactly one caller across threads *and*
  independent processes claims a bounded ownership lease under the short file
  lock; the others are skipped. When no marker exists (routine operation) the
  call is always allowed and requires no lease, so normal concurrent downloads
  are not serialized.
* ``finish_probe(transcripts_dir, decision, ..., now=None)`` -- called after the
  provider attempt with the outcome. Cooldown-clearing is ownership- and
  epoch-aware: only the process/thread that owns the current lease may clear, and
  only when the marker has not been renewed by a newer block behind its back. A
  confirmed ``blocked`` outcome always (re)enters the cooldown (never extending an
  already-active one). An unrelated failure or aborted probe releases the lease
  and arms a bounded probe backoff so probes never stampede.
* ``enter_block(transcripts_dir, ...)`` -- set/confirm the cooldown (used by the
  CLI on confirmed blocks and by tests); never extends an active cooldown and logs
  exactly one WARNING on each transition into blocked state.
* ``clear_block(transcripts_dir)`` -- operator reset: unconditionally remove the
  marker. Not used by normal ingest (see ``finish_probe``).
* ``probe_guard(transcripts_dir, now=None)`` -- retained as a thin in-process
  convenience wrapping ``begin_probe``/``finish_probe`` (see :func:`probe_guard`).

Configuration
-------------
Cooldown duration (default 3600 seconds):
* environment ``REF_YOUTUBE_TRANSCRIPT_BLOCK_COOLDOWN_SECONDS``, or
* config key ``youtube_transcript_block_cooldown_seconds``.

Operators can clear an active cooldown (e.g. after the ban lifts) by removing
``<transcripts_dir>/.youtube-transcript-block.json``.

Storage
-------
Marker: ``<transcripts_dir>/.youtube-transcript-block.json`` (atomic temp+rename)
Lock:   ``<transcripts_dir>/.youtube-transcript-block.lock`` (POSIX ``fcntl``)

The marker JSON also carries the probe lease and probe-backoff fields. Bounded
lease/backoff windows mean a crashed probe owner can never wedge ingestion.

If the marker cannot be persisted (e.g. read-only archive), a per-process
in-memory marker is used so capture is never aborted; cross-process suppression
degrades to process-local until the marker becomes writable.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 3600
ENV_COOLDOWN_SECONDS = "REF_YOUTUBE_TRANSCRIPT_BLOCK_COOLDOWN_SECONDS"
CONFIG_KEY_COOLDOWN_SECONDS = "youtube_transcript_block_cooldown_seconds"
MARKER_FILENAME = ".youtube-transcript-block.json"
LOCK_FILENAME = ".youtube-transcript-block.lock"
MARKER_VERSION = 1

# A recovery probe owns the marker lease for at most this long, so a crashed
# probe owner cannot wedge ingestion past it.
PROBE_LEASE_SECONDS = 300
# After an unrelated (non-block) probe failure, new probes are back off for this
# long so probes do not stampede into a repeated failure.
PROBE_BACKOFF_SECONDS = 60
# Absolute upper bound for a plausible epoch (year ~2100). A blocked_until beyond
# this is treated as malformed/unreasonable and ignored rather than wedging
# capture in an effectively-forever cooldown.
_MAX_PLAUSIBLE_EPOCH = 4_102_444_800.0

# In-process markup mirrors, only authoritative when the on-disk marker cannot be
# written (read-only archive). Kept separate so a process does not shadow newer
# cross-process updates once the disk is writable again.
_memory_state_lock = threading.Lock()
_memory_state: Dict[str, Dict[str, Any]] = {}
_memory_authoritative: set = set()

# Process-local critical section for marker read/modify/write. Always held (via
# ``_file_lock``) so the documented single-flight guarantee holds even when POSIX
# ``flock`` -- or the lock file itself -- is unavailable. Never held across
# provider I/O.
_process_state_lock = threading.RLock()


@dataclass
class ProbeDecision:
    """The outcome of :func:`begin_probe`.

    Attributes:
        allowed: True when the caller may attempt a provider transcript call.
        message: When ``allowed`` is False, a short user-facing reason
            (nonsecret) that the caller can embed in a queue/fallback outcome.
        owner: Lease token when this caller claims the recovery probe.
        epoch_blocked_until: The marker's ``blocked_until`` observed when the
            lease was claimed (used for stale-success protection).
        probing: True only when this caller actually owns the recovery probe
            lease (i.e. ``finish_probe`` must be called).
    """

    allowed: bool
    message: str = ""
    owner: Optional[str] = None
    epoch_blocked_until: float = 0.0
    probing: bool = False


def cooldown_seconds(config: Optional[dict] = None) -> int:
    """Resolve the configured cooldown duration in seconds."""
    raw_env = os.getenv(ENV_COOLDOWN_SECONDS)
    raw = raw_env
    if raw is None and config:
        raw = config.get(CONFIG_KEY_COOLDOWN_SECONDS)
    if raw is not None:
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            parsed = -1
        if parsed > 0:
            return parsed
        if raw_env is not None:
            logger.warning(
                "Ignoring non-positive %s=%r; using default %s seconds",
                ENV_COOLDOWN_SECONDS,
                raw_env,
                DEFAULT_COOLDOWN_SECONDS,
            )
    return DEFAULT_COOLDOWN_SECONDS


def marker_path(transcripts_dir: str) -> str:
    return os.path.join(transcripts_dir, MARKER_FILENAME)


def lock_path(transcripts_dir: str) -> str:
    return os.path.join(transcripts_dir, LOCK_FILENAME)


def _as_finite_nonneg(data: Dict[str, Any], key: str) -> Optional[float]:
    """Return a finite, non-negative float for ``key`` or None if malformed.

    ``float()`` of a huge-but-valid JSON integer (e.g. a 400-digit number) raises
    ``OverflowError``; that too must be treated as malformed, never raised.
    """
    try:
        value = float(data.get(key))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _as_int_nonneg(data: Dict[str, Any], key: str) -> int:
    try:
        value = float(data.get(key))
    except (TypeError, ValueError, OverflowError):
        return 0
    if not math.isfinite(value) or value < 0:
        return 0
    return int(value)


def _read_marker_unlocked(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    """Parse the on-disk marker, tolerating malformed/absent metadata.

    Never raises: any unexpected content results in ``None`` (treated as "not
    blocked") so API capture cannot fail solely because the marker is corrupt.
    """
    path = marker_path(transcripts_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    blocked_until = _as_finite_nonneg(data, "blocked_until")
    if blocked_until is None or blocked_until <= 0:
        return None
    if blocked_until > _MAX_PLAUSIBLE_EPOCH:
        logger.warning(
            "Ignoring implausible transcript block marker blocked_until=%r (<= %s)",
            data.get("blocked_until"),
            _MAX_PLAUSIBLE_EPOCH,
        )
        return None

    lease_owner = data.get("lease_owner")
    return {
        "blocked_until": blocked_until,
        "set_at": _as_finite_nonneg(data, "set_at") or 0.0,
        "duration_seconds": _as_int_nonneg(data, "duration_seconds"),
        "lease_owner": lease_owner if isinstance(lease_owner, str) else None,
        "lease_expires_at": _as_finite_nonneg(data, "lease_expires_at") or 0.0,
        "next_probe_at": _as_finite_nonneg(data, "next_probe_at") or 0.0,
    }


@contextlib.contextmanager
def _file_lock(transcripts_dir: str) -> Iterator[None]:
    """Critical section guarding marker read/modify/write.

    Always serializes within this process via ``_process_state_lock``, so the
    documented process-local single-flight guarantee holds even when POSIX
    locking, the archive directory or the lock file is unavailable. When POSIX
    ``flock`` works it additionally serializes independent processes sharing the
    archive. The lock is never held across provider I/O.
    """
    with _process_state_lock:
        try:
            import fcntl
        except ImportError:
            yield
            return
        try:
            os.makedirs(transcripts_dir, exist_ok=True)
        except OSError:
            yield
            return
        try:
            handle = open(lock_path(transcripts_dir), "a+", encoding="utf-8")
        except OSError:
            yield
            return
        with handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError:
                yield
                return
            try:
                yield
            finally:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass


def _memory_marker(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    with _memory_state_lock:
        return _memory_state.get(transcripts_dir)


def _read_effective_marker(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    """Read the marker, preferring the in-memory copy only when disk is broken."""
    with _memory_state_lock:
        authoritative = transcripts_dir in _memory_authoritative
        memory = _memory_state.get(transcripts_dir)
    if authoritative and memory is not None:
        return dict(memory)
    return _read_marker_unlocked(transcripts_dir)


def _atomic_write_marker(transcripts_dir: str, marker: Dict[str, Any]) -> None:
    os.makedirs(transcripts_dir, exist_ok=True)
    path = marker_path(transcripts_dir)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(marker, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _commit_marker(transcripts_dir: str, marker: Dict[str, Any]) -> None:
    """Persist the marker; on failure keep an in-memory copy (never abort)."""
    try:
        _atomic_write_marker(transcripts_dir, marker)
        with _memory_state_lock:
            _memory_authoritative.discard(transcripts_dir)
    except OSError as exc:
        logger.warning(
            "Could not persist YouTube transcript block marker in %r (%s); "
            "using in-process cooldown fallback for this run",
            transcripts_dir,
            exc,
        )
        with _memory_state_lock:
            _memory_state[transcripts_dir] = dict(marker)
            _memory_authoritative.add(transcripts_dir)


def read_marker(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    """Return the effective marker dict, or ``None`` when absent/unreadable."""
    return _read_effective_marker(transcripts_dir)


def is_blocked(transcripts_dir: str, now: Optional[float] = None) -> bool:
    """Return True while the cooldown suppresses provider transcript calls."""
    now = time.time() if now is None else now
    marker = _read_effective_marker(transcripts_dir)
    if marker is None:
        return False
    return now < marker["blocked_until"]


def blocked_until(transcripts_dir: str, now: Optional[float] = None) -> Optional[float]:
    """Return the effective cooldown expiry epoch, or None when not blocked."""
    now = time.time() if now is None else now
    marker = _read_effective_marker(transcripts_dir)
    if marker is None or now >= marker["blocked_until"]:
        return None
    return marker["blocked_until"]


def _format_deadline(deadline: float) -> str:
    dt_value = _dt.datetime.fromtimestamp(deadline, tz=_dt.timezone.utc)
    return dt_value.isoformat(timespec="seconds")


def _cooldown_message(marker: Dict[str, Any]) -> str:
    return (
        "YouTube transcript requests suppressed by IP cooldown until "
        f"{_format_deadline(marker['blocked_until'])} UTC"
    )


def _probe_backoff_message(deadline: float) -> str:
    return (
        "YouTube transcript recovery probe suppressed until "
        f"{_format_deadline(deadline)} UTC (after a failed probe)"
    )


def _probe_in_flight_message(deadline: float) -> str:
    return (
        "YouTube transcript recovery probe in progress by another process until "
        f"{_format_deadline(deadline)} UTC"
    )


def cooldown_message(transcripts_dir: str, now: Optional[float] = None) -> str:
    """Short sanitized message describing an active cooldown for user output."""
    now = time.time() if now is None else now
    marker = _read_effective_marker(transcripts_dir)
    if marker is None or now >= marker["blocked_until"]:
        return "YouTube transcript requests suppressed by IP cooldown"
    return _cooldown_message(marker)


def _new_owner() -> str:
    return f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"


def _enter_block_unlocked(
    transcripts_dir: str,
    now: float,
    duration: int,
    guidance_url: Optional[str],
) -> Dict[str, Any]:
    """Lock-held block entry; never extends an active cooldown. Logs one WARNING
    on each transition into blocked state."""
    existing = _read_effective_marker(transcripts_dir)
    if existing is not None and now < existing["blocked_until"]:
        return existing
    marker = {
        "version": MARKER_VERSION,
        "blocked_until": now + duration,
        "set_at": now,
        "duration_seconds": duration,
        "lease_owner": None,
        "lease_expires_at": 0.0,
        "next_probe_at": 0.0,
    }
    _commit_marker(transcripts_dir, marker)
    started = existing is None or now >= existing["blocked_until"]
    if started:
        transition = (
            "YouTube is blocking transcript requests from this IP; suppressing "
            "transcript fetches for %s seconds (until %s UTC)."
        )
        if guidance_url:
            transition += f" See {guidance_url} for working around IP bans."
        logger.warning(
            transition,
            marker["duration_seconds"],
            _format_deadline(marker["blocked_until"]),
        )
    return marker


def enter_block(
    transcripts_dir: str,
    duration_seconds: Optional[int] = None,
    now: Optional[float] = None,
    guidance_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Set (or confirm) the IP-block cooldown and return the effective marker.

    Uses a short, advisory-locked read-modify-write so concurrent CLI/API
    processes agree on a single expiry. An already-active cooldown is NOT
    extended by further processing. Exactly one WARNING is logged on each
    transition into blocked state.
    """
    now = time.time() if now is None else now
    duration = cooldown_seconds()
    if duration_seconds is not None and duration_seconds > 0:
        duration = int(duration_seconds)
    if duration <= 0:
        duration = DEFAULT_COOLDOWN_SECONDS

    with _file_lock(transcripts_dir):
        return _enter_block_unlocked(transcripts_dir, now, duration, guidance_url)


def _clear_marker_unlocked(transcripts_dir: str) -> None:
    try:
        os.remove(marker_path(transcripts_dir))
    except OSError:
        pass
    with _memory_state_lock:
        _memory_state.pop(transcripts_dir, None)
        _memory_authoritative.discard(transcripts_dir)


def clear_block(transcripts_dir: str) -> bool:
    """Operator reset: unconditionally clear any marker. Best-effort."""
    removed = False
    with _file_lock(transcripts_dir):
        if _read_effective_marker(transcripts_dir) is not None:
            _clear_marker_unlocked(transcripts_dir)
            removed = True
        else:
            with _memory_state_lock:
                _memory_state.pop(transcripts_dir, None)
                _memory_authoritative.discard(transcripts_dir)
    return removed


def begin_probe(transcripts_dir: str, now: Optional[float] = None) -> ProbeDecision:
    """Claim the right to attempt a transcript provider call for ``transcripts_dir``.

    Returns a :class:`ProbeDecision`. Guarded by the short file lock so exactly
    one recovery probe is ever active across threads *and* independent processes
    sharing the archive. Routine downloads (no marker on disk) need no lease and
    are never serialized. When the marker cannot be persisted the lease is kept
    in-process only, degrading cross-process single-flight to process-local.
    """
    now = time.time() if now is None else now

    def _decide() -> ProbeDecision:
        marker = _read_effective_marker(transcripts_dir)
        if marker is None:
            return ProbeDecision(allowed=True)
        if now < marker["blocked_until"]:
            return ProbeDecision(allowed=False, message=_cooldown_message(marker))
        if marker["next_probe_at"] > now:
            return ProbeDecision(
                allowed=False, message=_probe_backoff_message(marker["next_probe_at"])
            )
        if marker["lease_expires_at"] > now:
            return ProbeDecision(
                allowed=False,
                message=_probe_in_flight_message(marker["lease_expires_at"]),
            )
        # The cooldown expired and no one owns the recovery probe: claim it.
        owner = _new_owner()
        updated = dict(marker)
        updated["lease_owner"] = owner
        updated["lease_expires_at"] = now + PROBE_LEASE_SECONDS
        _commit_marker(transcripts_dir, updated)
        return ProbeDecision(
            allowed=True,
            owner=owner,
            epoch_blocked_until=marker["blocked_until"],
            probing=True,
        )

    with _file_lock(transcripts_dir):
        return _decide()


def finish_probe(
    transcripts_dir: str,
    decision: ProbeDecision,
    *,
    transcript_file: Optional[str] = None,
    failure_info: Optional[tuple] = None,
    duration_seconds: Optional[int] = None,
    guidance_url: Optional[str] = None,
    video_id: Optional[str] = None,
    now: Optional[float] = None,
) -> None:
    """Close out a probe attempt with the observed outcome (single call site).

    * confirmed block: (re)enter the cooldown (never extends an active one) and
      log the single transition warning; the blocker always takes precedence.
    * success: clear the cooldown only if this caller still owns the lease and
      the marker has not been renewed behind its back (prevents a stale success
      from erasing a newer cooldown). Otherwise leave the marker intact.
    * unrelated failure / aborted probe: release the lease and arm the bounded
      probe backoff so the next probe is a single, later attempt (no stampede).

    Routine (non-probe) successes and failures never mutate the marker.
    """
    if failure_info is not None and failure_info[0] == "blocked":
        with _file_lock(transcripts_dir):
            _enter_block_unlocked(
                transcripts_dir,
                time.time() if now is None else now,
                duration_seconds or cooldown_seconds(),
                guidance_url,
            )
            if decision.probing:
                # Release our lease slot; the cooldown itself now gates callers.
                marker = _read_effective_marker(transcripts_dir)
                if marker is not None and marker.get("lease_owner") == decision.owner:
                    marker["lease_owner"] = None
                    marker["lease_expires_at"] = 0.0
                    _commit_marker(transcripts_dir, marker)
        return

    if not decision.probing:
        # Routine operation (no cooldown in play): never clear or renew on behalf
        # of anyone, and never arm a backoff.
        return

    now = time.time() if now is None else now
    success = transcript_file is not None

    def _owns_current_epoch(marker: Dict[str, Any]) -> bool:
        return (
            marker.get("lease_owner") == decision.owner
            and marker["blocked_until"] == decision.epoch_blocked_until
        )

    def _finish_probing() -> None:
        marker = _read_effective_marker(transcripts_dir)
        if marker is None:
            # Another producer already cleared the marker (its own success). There
            # is nothing to protect; our job is done.
            return
        if not _owns_current_epoch(marker):
            # Either a newer owner claimed the recovery lease or a newer block
            # epoch replaced ours. A stale success/failure from an older probe
            # must leave the entire newer marker untouched: never clear a newer
            # cooldown, never seize another owner's lease, never arm a backoff on
            # someone else's behalf.
            return
        if success:
            _clear_marker_unlocked(transcripts_dir)
            return
        # Unrelated failure / abort from the CURRENT owner of the CURRENT epoch:
        # release our own lease and arm a bounded backoff.
        marker["lease_owner"] = None
        marker["lease_expires_at"] = 0.0
        marker["next_probe_at"] = now + PROBE_BACKOFF_SECONDS
        _commit_marker(transcripts_dir, marker)

    with _file_lock(transcripts_dir):
        _finish_probing()


@contextlib.contextmanager
def probe_guard(transcripts_dir: str, now: Optional[float] = None) -> Iterator[ProbeDecision]:
    """Context-manager convenience over :func:`begin_probe`.

    Yields a :class:`ProbeDecision`. The caller is responsible for calling
    :func:`finish_probe` with the real outcome; an abandoned lease is bounded by
    :data:`PROBE_LEASE_SECONDS`, so a crash can never wedge ingestion.
    """
    yield begin_probe(transcripts_dir, now=now)
