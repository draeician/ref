"""Durable ref-api state beside the archive (JSON, same architecture as the queue).

Two small stores live here:

* :class:`UrlIdentityStore` records the authoritative ``original -> stored`` URL
  mapping after a confirmed capture.  It is what lets ``GET /urls/exists``
  distinguish a persisted canonical match from a guess after a process restart.
* :class:`IdempotencyStore` records request state for ``POST /urls`` with an
  ``Idempotency-Key``.  Entries are written before work starts and updated after
  each input, so an interrupted request can be reconciled rather than blindly
  re-executed.

Both use the same conventions as ``show_notes_queue``: a filesystem directory
beside ``references.md``, atomic temp-file + ``os.replace`` writes, process-local
locking, and fail-closed loading (a corrupt file is never overwritten).
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from ref_api.atomic_json import atomic_write_json

IDENTITY_FILENAME = "url_identities.json"
IDEMPOTENCY_FILENAME = "idempotency.json"

STATE_VERSION = 1

# Bounded state. In-progress and ambiguous requests are never pruned.
MAX_IDENTITIES = 5000
MAX_IDEMPOTENCY_REQUESTS = 1000
IDEMPOTENCY_RETENTION_SECONDS = 30 * 24 * 60 * 60


class StateStoreError(RuntimeError):
    """A state file exists but is unreadable, malformed or schema-invalid."""


class IdempotencyConflict(StateStoreError):
    """The same idempotency key was reused with a different payload."""


class IdempotencyAmbiguous(StateStoreError):
    """An interrupted forced operation cannot be reconciled without risk.

    Raised fail-closed instead of repeating an archive write that may already
    have committed.
    """


def _read_object(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return None
    except OSError as exc:  # noqa: BLE001 - unreadable is not fresh
        raise StateStoreError(f"state file is unreadable: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - malformed is always fail-closed
        raise StateStoreError(f"state file is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise StateStoreError("state file is not a JSON object")
    return data


class UrlIdentityStore:
    """Persisted exact original -> stored URL identity ledger."""

    def __init__(self, state_dir: str) -> None:
        self.path = os.path.join(state_dir, IDENTITY_FILENAME)
        self._lock = threading.RLock()
        self._loaded = False
        self._identities: Dict[str, Dict[str, Any]] = {}

    def _load(self) -> None:
        if self._loaded:
            return
        data = _read_object(self.path)
        if data is None:
            self._identities = {}
            self._loaded = True
            return
        if data.get("version") != STATE_VERSION:
            raise StateStoreError("unsupported url identity version")
        identities = data.get("identities")
        if not isinstance(identities, dict):
            raise StateStoreError("missing 'identities' map")
        normalized: Dict[str, Dict[str, Any]] = {}
        for original, entry in identities.items():
            if not isinstance(original, str) or not original:
                raise StateStoreError(f"invalid identity key {original!r}")
            if not isinstance(entry, dict):
                raise StateStoreError(f"identity {original!r} is not an object")
            stored = entry.get("url")
            if not isinstance(stored, str) or not stored:
                raise StateStoreError(f"identity {original!r} has no url")
            updated_at = entry.get("updated_at")
            if isinstance(updated_at, bool) or not isinstance(updated_at, (int, float)):
                raise StateStoreError(f"identity {original!r} has invalid updated_at")
            normalized[original] = {"url": stored, "updated_at": float(updated_at)}
        self._identities = normalized
        self._loaded = True

    def _prune(self, identities: Dict[str, Dict[str, Any]]) -> None:
        if len(identities) <= MAX_IDENTITIES:
            return
        ordered = sorted(
            identities.items(), key=lambda item: item[1].get("updated_at", 0.0)
        )
        for original, _entry in ordered[: len(ordered) - MAX_IDENTITIES]:
            identities.pop(original, None)

    def _save(self, identities: Dict[str, Dict[str, Any]]) -> None:
        self._prune(identities)
        atomic_write_json(
            self.path,
            {"version": STATE_VERSION, "identities": identities},
        )

    def record(self, original: str, stored_url: str) -> None:
        original = (original or "").strip()
        stored_url = (stored_url or "").strip()
        if not original or not stored_url:
            return
        with self._lock:
            self._load()
            existing = self._identities.get(original)
            if existing and existing.get("url") == stored_url:
                return
            identities = {
                key: dict(entry) for key, entry in self._identities.items()
            }
            identities[original] = {
                "url": stored_url,
                "updated_at": time.time(),
            }
            # Persist first; publish the new ledger only after the write commits.
            self._save(identities)
            self._identities = identities

    def lookup(self, original: str) -> Optional[str]:
        original = (original or "").strip()
        if not original:
            return None
        with self._lock:
            self._load()
            entry = self._identities.get(original)
            if not entry:
                return None
            return str(entry["url"])


class IdempotencyStore:
    """Durable, bounded request-state table for ``Idempotency-Key`` submissions."""

    def __init__(self, state_dir: str) -> None:
        self.path = os.path.join(state_dir, IDEMPOTENCY_FILENAME)
        self._lock = threading.RLock()
        self._key_locks: Dict[str, threading.RLock] = {}
        self._loaded = False
        self._requests: Dict[str, Dict[str, Any]] = {}

    @contextmanager
    def key_lock(self, key: str) -> Iterator[None]:
        """Serialize all work for one idempotency key inside this process."""
        with self._lock:
            lock = self._key_locks.setdefault(key, threading.RLock())
        with lock:
            yield

    def _load(self) -> None:
        if self._loaded:
            return
        data = _read_object(self.path)
        if data is None:
            self._requests = {}
            self._loaded = True
            return
        if data.get("version") != STATE_VERSION:
            raise StateStoreError("unsupported idempotency version")
        requests = data.get("requests")
        if not isinstance(requests, dict):
            raise StateStoreError("missing 'requests' map")
        normalized: Dict[str, Dict[str, Any]] = {}
        for key, entry in requests.items():
            if not isinstance(key, str) or not key:
                raise StateStoreError(f"invalid idempotency key {key!r}")
            if not isinstance(entry, dict):
                raise StateStoreError(f"idempotency request {key!r} is not an object")
            request_hash = entry.get("request_hash")
            inputs = entry.get("inputs")
            state = entry.get("state")
            results = entry.get("results")
            attempts = entry.get("attempts")
            created_at = entry.get("created_at")
            updated_at = entry.get("updated_at")
            error = entry.get("error", "")
            if not isinstance(request_hash, str) or not request_hash:
                raise StateStoreError(f"idempotency request {key!r} has no hash")
            if not isinstance(inputs, list) or not all(
                isinstance(item, str) for item in inputs
            ):
                raise StateStoreError(f"idempotency request {key!r} has invalid inputs")
            if state not in ("processing", "completed", "ambiguous"):
                raise StateStoreError(f"idempotency request {key!r} has invalid state")
            if not isinstance(results, list) or not all(
                item is None or isinstance(item, dict) for item in results
            ):
                raise StateStoreError(f"idempotency request {key!r} has invalid results")
            force = entry.get("force", False)
            if not isinstance(force, bool):
                raise StateStoreError(f"idempotency request {key!r} has invalid force")
            if attempts is None:
                attempts = [None] * len(inputs)
            if not isinstance(attempts, list) or len(attempts) != len(inputs):
                raise StateStoreError(
                    f"idempotency request {key!r} has invalid attempts"
                )
            normalized_attempts: List[Optional[Dict[str, Any]]] = []
            for attempt in attempts:
                if attempt is None:
                    normalized_attempts.append(None)
                    continue
                if not isinstance(attempt, dict):
                    raise StateStoreError(
                        f"idempotency request {key!r} has invalid attempt"
                    )
                fingerprint = attempt.get("fingerprint")
                started_at = attempt.get("started_at")
                if not isinstance(fingerprint, str) or not fingerprint:
                    raise StateStoreError(
                        f"idempotency request {key!r} attempt has no fingerprint"
                    )
                if isinstance(started_at, bool) or not isinstance(
                    started_at, (int, float)
                ):
                    raise StateStoreError(
                        f"idempotency request {key!r} attempt has invalid started_at"
                    )
                normalized_attempts.append(
                    {"fingerprint": fingerprint, "started_at": float(started_at)}
                )
            for value, field in (
                (created_at, "created_at"),
                (updated_at, "updated_at"),
            ):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise StateStoreError(
                        f"idempotency request {key!r} has invalid {field}"
                    )
            if not isinstance(error, str):
                raise StateStoreError(f"idempotency request {key!r} has invalid error")
            normalized[key] = {
                "request_hash": request_hash,
                "inputs": list(inputs),
                "force": force,
                "state": state,
                "results": results,
                "attempts": normalized_attempts,
                "error": error,
                "created_at": float(created_at),
                "updated_at": float(updated_at),
            }
        self._requests = normalized
        self._loaded = True

    def _prune(self, requests: Dict[str, Dict[str, Any]]) -> None:
        now = time.time()
        completed = [
            (key, entry)
            for key, entry in requests.items()
            if entry.get("state") == "completed"
            and now - entry.get("updated_at", 0.0) > IDEMPOTENCY_RETENTION_SECONDS
        ]
        for key, _entry in completed:
            requests.pop(key, None)
        if len(requests) <= MAX_IDEMPOTENCY_REQUESTS:
            return
        prunable = sorted(
            (
                (key, entry)
                for key, entry in requests.items()
                if entry.get("state") == "completed"
            ),
            key=lambda item: item[1].get("updated_at", 0.0),
        )
        excess = len(requests) - MAX_IDEMPOTENCY_REQUESTS
        for key, _entry in prunable[:excess]:
            requests.pop(key, None)

    def _save(self, requests: Dict[str, Dict[str, Any]]) -> None:
        self._prune(requests)
        atomic_write_json(
            self.path,
            {"version": STATE_VERSION, "requests": requests},
        )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._load()
            entry = self._requests.get(key)
            return dict(entry) if entry is not None else None

    def begin(
        self,
        key: str,
        *,
        request_hash: str,
        inputs: List[str],
        force: bool,
    ) -> Dict[str, Any]:
        """Return the current request entry, creating it when new.

        Raises :class:`IdempotencyConflict` when the key was already used with a
        different request hash, and :class:`IdempotencyAmbiguous` when an earlier
        attempt is unresolved and must not be re-executed.
        """
        with self._lock:
            self._load()
            existing = self._requests.get(key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "Idempotency-Key was already used with a different request payload"
                    )
                if existing["state"] == "ambiguous":
                    raise IdempotencyAmbiguous(
                        "Idempotency-Key is ambiguous after an interrupted forced "
                        "operation; inspect GET /requests/{key} and use a new key "
                        "if another forced capture is intended"
                    )
                return dict(existing)
            now = time.time()
            entry = {
                "request_hash": request_hash,
                "inputs": list(inputs),
                "force": bool(force),
                "state": "processing",
                "results": [None] * len(inputs),
                "attempts": [None] * len(inputs),
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
            requests = {
                request_key: dict(request_entry)
                for request_key, request_entry in self._requests.items()
            }
            requests[key] = entry
            self._save(requests)
            self._requests = requests
            return dict(entry)

    def update(
        self,
        key: str,
        *,
        results: List[Optional[Dict[str, Any]]],
        attempts: Optional[List[Optional[Dict[str, Any]]]] = None,
        error: str = "",
        completed: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            self._load()
            entry = self._requests.get(key)
            if entry is None:
                raise StateStoreError(f"idempotency request {key!r} disappeared")
            requests = {
                request_key: dict(request_entry)
                for request_key, request_entry in self._requests.items()
            }
            updated = requests[key]
            updated["results"] = list(results)
            if attempts is not None:
                if len(attempts) != len(updated["inputs"]):
                    raise StateStoreError(
                        f"idempotency request {key!r} attempt count mismatch"
                    )
                updated["attempts"] = list(attempts)
            updated["error"] = error[:2000]
            updated["state"] = "completed" if completed else "processing"
            updated["updated_at"] = time.time()
            self._save(requests)
            self._requests = requests
            return dict(updated)

    def mark_ambiguous(
        self,
        key: str,
        *,
        results: List[Optional[Dict[str, Any]]],
        attempts: List[Optional[Dict[str, Any]]],
        error: str,
    ) -> Dict[str, Any]:
        """Persist an explicit fail-closed state after an unreconcilable crash."""
        with self._lock:
            self._load()
            if key not in self._requests:
                raise StateStoreError(f"idempotency request {key!r} disappeared")
            requests = {
                request_key: dict(request_entry)
                for request_key, request_entry in self._requests.items()
            }
            updated = requests[key]
            if len(attempts) != len(updated["inputs"]):
                raise StateStoreError(
                    f"idempotency request {key!r} attempt count mismatch"
                )
            updated["results"] = list(results)
            updated["attempts"] = list(attempts)
            updated["state"] = "ambiguous"
            updated["error"] = error[:2000]
            updated["updated_at"] = time.time()
            self._save(requests)
            self._requests = requests
            return dict(updated)
