"""Structured primary-capture results.

The CLI has historically reported its outcome by printing human-readable text.
That text is convenient for terminals but is not authoritative for API clients:
a nested child URL can print the same "already recorded" / reference line as the
primary URL.  This module records the outcome at the point where the archive
write (or an exact existing-row check) actually happens.

Only the top-level capture frame is recorded.  ``process_url`` enters a nested
frame for recursive child processing, so a child can never overwrite the primary
result.  The recorder is thread-local because ``ref-api`` processes independent
requests (and the background worker) concurrently.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

_PRIMARY_STATUSES = frozenset({"added", "exists"})

# Keep diagnostics bounded and avoid spreading obviously sensitive URL
# credentials / token-like query values into logs or API responses.
_SECRET_QUERY_RE = re.compile(
    r"(?i)((?:[?&#]|\b)[^=&#\s]*?"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|"
    r"passwd|signature|sig|credential)[^=&#\s]*=)[^&#\s]+"
)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/@\s]+@")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def redact_credentials(text: object) -> str:
    """Redact URL userinfo and token-bearing query/fragment values.

    Does not flatten or truncate, so callers that need to preserve line breaks
    (for example file logs) can use it directly.
    """
    value = str(text or "")
    value = _URL_USERINFO_RE.sub(r"\1***@", value)
    value = _SECRET_QUERY_RE.sub(r"\1***", value)
    return value


def sanitize_error_detail(text: object, *, limit: int = 300) -> str:
    """Return a one-line, bounded, credential-redacted diagnostic string."""
    value = redact_credentials(text).replace("\r", " ").replace("\n", " ")
    value = _CONTROL_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value


@dataclass(frozen=True)
class CaptureResult:
    """Authoritative result of a primary archive capture."""

    status: str
    url: str
    source: str = ""


@dataclass
class _CaptureState:
    active: bool = False
    depth: int = 0
    call_depth: int = 0
    result: Optional[CaptureResult] = None
    error: str = ""


_state = threading.local()


def _thread_state() -> _CaptureState:
    state = getattr(_state, "capture", None)
    if state is None:
        state = _CaptureState()
        _state.capture = state
    return state


@contextmanager
def capture_scope():
    """Open a primary-capture scope for one caller request.

    Nested scopes share the outermost state.  Entering at depth zero clears any
    previous result, so a reused worker thread cannot leak a capture between
    requests.
    """
    state = _thread_state()
    if state.depth == 0:
        state.active = True
        state.result = None
        state.error = ""
        state.call_depth = 0
    state.depth += 1
    try:
        yield state
    finally:
        state.depth -= 1
        if state.depth == 0:
            state.active = False


@contextmanager
def capture_frame():
    """Mark one ``process_url`` call; nested calls are child frames."""
    state = _thread_state()
    state.call_depth += 1
    try:
        yield
    finally:
        state.call_depth -= 1


def record_primary(status: str, url: str, *, source: str = "") -> None:
    """Record the primary outcome from an actual archive write / exact check.

    Ignored outside a :func:`capture_scope`, for child frames, and after a
    primary result has already been recorded.  This first-writer rule is what
    prevents child ingestion from changing the primary result.
    """
    if status not in _PRIMARY_STATUSES:
        return
    value = (url or "").strip()
    if not value:
        return
    state = _thread_state()
    if not state.active or state.call_depth > 1:
        return
    if state.result is None:
        state.result = CaptureResult(status=status, url=value, source=source)


def record_error(message: object) -> None:
    """Record a sanitized primary failure when no capture has succeeded."""
    state = _thread_state()
    if not state.active or state.call_depth > 1:
        return
    if state.result is not None or state.error:
        return
    state.error = sanitize_error_detail(message)


def current_capture() -> tuple[Optional[CaptureResult], str]:
    """Return ``(result, sanitized_error)`` for the current thread."""
    state = _thread_state()
    return state.result, state.error


def reset_capture() -> None:
    """Clear thread-local capture state (test/utility helper)."""
    state = _thread_state()
    state.active = False
    state.depth = 0
    state.call_depth = 0
    state.result = None
    state.error = ""
