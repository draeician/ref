"""Persisted YouTube transcript IP-block cooldown.

When YouTube blocks transcript requests from this host's public IP, ``ref`` stops
calling ``youtube-transcript-api`` for a configurable window so an IP-ban request
storm cannot keep compounding already-slow synchronous ingests with per-video
blocked fetches and repeated warnings.

The expiry marker lives in the archive's transcripts state directory (outside the
repository) so separate CLI and API processes sharing the archive all honour the
same cooldown and it survives service restarts.

Interface (used by ``ref_cli.cli``):

* ``is_blocked(transcripts_dir, now=None)`` -- should provider transcript calls be
  suppressed right now?
* ``probe_guard(transcripts_dir)`` -- context manager wrapping a provider attempt.
  Serializes probes within this process and yields ``False`` when a cooldown is
  active (or an in-process probe already re-entered one) so the caller skips the
  remote call; yields ``True`` when the caller may probe.
* ``enter_block(transcripts_dir, duration_seconds=None, now=None)`` -- persist a
  fresh cooldown expiry. Recognizes an already-active cooldown and does NOT extend
  it. Logs exactly one WARNING on the transition into blocked state.
* ``clear_block(transcripts_dir)`` -- clear the marker (a probe succeeded).

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

If the marker cannot be persisted (e.g. read-only archive), a per-process
in-memory marker is used so capture is never aborted; cross-process suppression
degrades to process-local until the marker becomes writable.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import threading
import time
from typing import Any, Dict, Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_COOLDOWN_SECONDS = 3600
ENV_COOLDOWN_SECONDS = "REF_YOUTUBE_TRANSCRIPT_BLOCK_COOLDOWN_SECONDS"
CONFIG_KEY_COOLDOWN_SECONDS = "youtube_transcript_block_cooldown_seconds"
MARKER_FILENAME = ".youtube-transcript-block.json"
LOCK_FILENAME = ".youtube-transcript-block.lock"
MARKER_VERSION = 1

# Serializes provider probes within this process (in-process stampede suppression).
_probe_lock = threading.Lock()
# In-process fallback state used when the marker cannot be persisted.
_memory_state_lock = threading.Lock()
_memory_state: Dict[str, Dict[str, Any]] = {}


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


def _read_marker_unlocked(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    path = marker_path(transcripts_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        blocked_until = float(data.get("blocked_until", 0.0))
    except (TypeError, ValueError):
        return None
    if blocked_until <= 0:
        return None
    return {
        "blocked_until": blocked_until,
        "set_at": float(data.get("set_at", 0.0) or 0.0),
        "duration_seconds": int(data.get("duration_seconds", 0) or 0),
    }


@contextlib.contextmanager
def _file_lock(transcripts_dir: str) -> Iterator[None]:
    """Advisory lock protecting marker read-modify-write (POSIX)."""
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


def read_marker(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    """Return the on-disk marker dict, or ``None`` when absent/unreadable."""
    return _read_marker_unlocked(transcripts_dir)


def _memory_marker(transcripts_dir: str) -> Optional[Dict[str, Any]]:
    with _memory_state_lock:
        return _memory_state.get(transcripts_dir)


def is_blocked(transcripts_dir: str, now: Optional[float] = None) -> bool:
    """Return True while the cooldown suppresses provider transcript calls."""
    now = time.time() if now is None else now
    memory_marker = _memory_marker(transcripts_dir)
    if memory_marker and now < float(memory_marker.get("blocked_until", 0.0)):
        return True
    marker = _read_marker_unlocked(transcripts_dir)
    if marker is None:
        return False
    return now < marker["blocked_until"]


def blocked_until(transcripts_dir: str, now: Optional[float] = None) -> Optional[float]:
    """Return the effective cooldown expiry epoch, or None when not blocked."""
    now = time.time() if now is None else now
    memory_marker = _memory_marker(transcripts_dir)
    if memory_marker and now < float(memory_marker.get("blocked_until", 0.0)):
        return float(memory_marker["blocked_until"])
    marker = _read_marker_unlocked(transcripts_dir)
    if marker is None or now >= marker["blocked_until"]:
        return None
    return marker["blocked_until"]


def _format_deadline(deadline: float) -> str:
    dt_value = _dt.datetime.fromtimestamp(deadline, tz=_dt.timezone.utc)
    return dt_value.isoformat(timespec="seconds")


def cooldown_message(transcripts_dir: str, now: Optional[float] = None) -> str:
    """Short sanitized message describing an active cooldown for user output."""
    deadline = blocked_until(transcripts_dir, now=now)
    if deadline is None:
        return "YouTube transcript requests suppressed by IP cooldown"
    return (
        "YouTube transcript requests suppressed by IP cooldown until "
        f"{_format_deadline(deadline)} UTC"
    )


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


def enter_block(
    transcripts_dir: str,
    duration_seconds: Optional[int] = None,
    now: Optional[float] = None,
    guidance_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Set (or confirm) the IP-block cooldown and return the effective marker.

    Uses a short, advisory-locked read-modify-write so concurrent CLI/API
    processes agree on a single expiry. An already-active cooldown is NOT
    extended by further processing. Exactly one WARNING is logged on the
    transition into blocked state.
    """
    now = time.time() if now is None else now
    duration = cooldown_seconds()
    if duration_seconds is not None and duration_seconds > 0:
        duration = int(duration_seconds)
    if duration <= 0:
        duration = DEFAULT_COOLDOWN_SECONDS

    marker: Optional[Dict[str, Any]] = None
    entered_now = False

    def _read_modify_write() -> None:
        nonlocal marker, entered_now
        existing = _read_marker_unlocked(transcripts_dir)
        if existing is not None and now < existing["blocked_until"]:
            marker = existing
            return
        new_marker = {
            "version": MARKER_VERSION,
            "blocked_until": now + duration,
            "set_at": now,
            "duration_seconds": duration,
        }
        try:
            _atomic_write_marker(transcripts_dir, new_marker)
        except OSError as exc:
            logger.warning(
                "Could not persist YouTube transcript block marker in %r (%s); "
                "using in-process cooldown fallback for this run",
                transcripts_dir,
                exc,
            )
        with _memory_state_lock:
            _memory_state[transcripts_dir] = new_marker
        marker = new_marker
        entered_now = True

    with _file_lock(transcripts_dir):
        _read_modify_write()

    if entered_now and marker is not None:
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
    return marker  # type: ignore[return-value]


def clear_block(transcripts_dir: str) -> bool:
    """Clear any active cooldown (a fresh probe succeeded). Best-effort."""
    with _memory_state_lock:
        _memory_state.pop(transcripts_dir, None)
    removed = False
    with _file_lock(transcripts_dir):
        if _read_marker_unlocked(transcripts_dir) is not None:
            try:
                os.remove(marker_path(transcripts_dir))
                removed = True
            except OSError:
                removed = False
    return removed


@contextlib.contextmanager
def probe_guard(transcripts_dir: str, now: Optional[float] = None) -> Iterator[bool]:
    """Serialize provider probes within this process.

    Yields True when the caller may attempt a provider transcript fetch, and
    False when cooldown is active (or an in-process probe already re-entered it)
    so the caller skips the remote call without contacting YouTube.
    Cross-process stampede prevention relies on the atomic marker; a fully
    distributed probe lease is deferred (would require a scheduler/control plane).
    """
    with _probe_lock:
        if is_blocked(transcripts_dir, now=now):
            yield False
        else:
            yield True
