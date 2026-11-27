"""Atomic JSON writes shared by the show-notes queue and ref-api state stores.

Guarantees (single writing process, caller-serialized):

* The complete payload is written to a unique temporary file in the target
  directory, flushed to the OS and ``fsync``-ed before it can replace the
  target.  A failure while writing or syncing leaves the previous target
  untouched and removes the temporary file.
* ``os.replace`` is the commit point.  A reader sees either the previous
  complete file or the new complete file, never a partial write.
* After a successful replace, the parent directory is ``fsync``-ed on a
  best-effort basis so the rename itself is durable on filesystems that support
  directory fsync.  Failure to sync the directory is logged but is not reported
  as a failed write, because the rename has already committed.
* Atomic replacement is not cross-process mutual exclusion.  Callers serialize
  mutations with their own process-local locks; the queue/store are designed for
  a single ``ref-api`` process.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _fsync_directory(directory: str) -> None:
    """Best-effort directory fsync after a rename (not supported everywhere)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as exc:  # noqa: BLE001 - rename already committed
        logger.warning("Could not open directory for fsync %s: %s", directory, exc)
        return
    try:
        os.fsync(fd)
    except OSError as exc:  # noqa: BLE001 - rename already committed
        logger.warning("Could not fsync directory %s: %s", directory, exc)
    finally:
        os.close(fd)


def atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    """Write ``payload`` as JSON to ``path`` with an atomic replace commit."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # Never leave a failed attempt looking like an accepted write.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    _fsync_directory(directory)
