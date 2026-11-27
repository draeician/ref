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

IDENTITY_FILENAME = "url_identities.json"
IDEMPOTENCY_FILENAME = "idempotency.json"

STATE_VERSION = 1

# Bounded state. In-progress idempotency requests are never pruned.
MAX_IDENTITIES = 5000
MAX_IDEMPOTENCY_REQUESTS = 1000
IDEMPOTENCY_RETENTION_SECONDS = 30 * 24 * 60 * 60


class StateStoreError(RuntimeError):
    """A state file exists but is unreadable, malformed or schema-invalid."""


class IdempotencyConflict(StateStoreError):
    """The same idempotency key was reused with a different payload."""


def _atomic_write(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


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

    def _prune(self) -> None:
        if len(self._identities) <= MAX_IDENTITIES:
            return
        ordered = sorted(
            self._identities.items(), key=lambda item: item[1].get("updated_at", 0.0)
        )
        for original, _entry in ordered[: len(ordered) - MAX_IDENTITIES]:
            self._identities.pop(original, None)

    def _save(self) -> None:
        self._prune()
        _atomic_write(
            self.path,
            {"version": STATE_VERSION, "identities": self._identities},
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
            self._identities[original] = {
                "url": stored_url,
                "updated_at": time.time(),
            }
            self._save()

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
            created_at = entry.get("created_at")
            updated_at = entry.get("updated_at")
            error = entry.get("error", "")
            if not isinstance(request_hash, str) or not request_hash:
                raise StateStoreError(f"idempotency request {key!r} has no hash")
            if not isinstance(inputs, list) or not all(
                isinstance(item, str) for item in inputs
            ):
                raise StateStoreError(f"idempotency request {key!r} has invalid inputs")
            if state not in ("processing", "completed"):
                raise StateStoreError(f"idempotency request {key!r} has invalid state")
            if not isinstance(results, list):
                raise StateStoreError(f"idempotency request {key!r} has invalid results")
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
                "force": bool(entry.get("force", False)),
                "state": state,
                "results": results,
                "error": error,
                "created_at": float(created_at),
                "updated_at": float(updated_at),
            }
        self._requests = normalized
        self._loaded = True

    def _prune(self) -> None:
        now = time.time()
        completed = [
            (key, entry)
            for key, entry in self._requests.items()
            if entry.get("state") == "completed"
            and now - entry.get("updated_at", 0.0) > IDEMPOTENCY_RETENTION_SECONDS
        ]
        for key, _entry in completed:
            self._requests.pop(key, None)
        if len(self._requests) <= MAX_IDEMPOTENCY_REQUESTS:
            return
        prunable = sorted(
            (
                (key, entry)
                for key, entry in self._requests.items()
                if entry.get("state") == "completed"
            ),
            key=lambda item: item[1].get("updated_at", 0.0),
        )
        excess = len(self._requests) - MAX_IDEMPOTENCY_REQUESTS
        for key, _entry in prunable[:excess]:
            self._requests.pop(key, None)

    def _save(self) -> None:
        self._prune()
        _atomic_write(
            self.path,
            {"version": STATE_VERSION, "requests": self._requests},
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
        different request hash.
        """
        with self._lock:
            self._load()
            existing = self._requests.get(key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "Idempotency-Key was already used with a different request payload"
                    )
                return dict(existing)
            now = time.time()
            entry = {
                "request_hash": request_hash,
                "inputs": list(inputs),
                "force": bool(force),
                "state": "processing",
                "results": [],
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
            self._requests[key] = entry
            self._save()
            return dict(entry)

    def update(
        self,
        key: str,
        *,
        results: List[Dict[str, Any]],
        error: str = "",
        completed: bool = False,
    ) -> Dict[str, Any]:
        with self._lock:
            self._load()
            entry = self._requests.get(key)
            if entry is None:
                raise StateStoreError(f"idempotency request {key!r} disappeared")
            entry["results"] = list(results)
            entry["error"] = error[:2000]
            entry["state"] = "completed" if completed else "processing"
            entry["updated_at"] = time.time()
            self._save()
            return dict(entry)
