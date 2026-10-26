"""YouTube transcript mode and durable local-transcribe queue configuration."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

MODE_REMOTE_FIRST = "remote_first"
MODE_LOCAL_ONLY = "local_only"
DEFAULT_MODE = MODE_REMOTE_FIRST

ENV_MODE = "REF_YOUTUBE_TRANSCRIPT_MODE"
CONFIG_KEY_MODE = "youtube_transcript_mode"
ENV_LT_PATH = "REF_LOCAL_TRANSCRIBE_LT"
CONFIG_KEY_LT_PATH = "local_transcribe_lt"
ENV_QUEUE_DIR = "REF_LOCAL_TRANSCRIBE_QUEUE_DIR"
CONFIG_KEY_QUEUE_DIR = "local_transcribe_queue_dir"
ENV_QUEUE_UUID = "REF_LOCAL_TRANSCRIBE_QUEUE_UUID"
CONFIG_KEY_QUEUE_UUID = "local_transcribe_queue_uuid"


class TranscriptQueueConfigError(RuntimeError):
    """Configured transcript queue settings are invalid or unusable."""


class TranscriptQueueUnavailable(TranscriptQueueConfigError):
    """The configured queue directory or identity marker is unavailable."""


def _setting(
    config: Optional[Mapping[str, Any]],
    env_name: str,
    config_key: str,
) -> tuple[Optional[str], Optional[str]]:
    raw = os.getenv(env_name)
    if raw is not None and raw.strip():
        return raw.strip(), env_name
    if config:
        value = config.get(config_key)
        if value is not None and str(value).strip():
            return str(value).strip(), config_key
    return None, None


def resolve_mode(config: Optional[Mapping[str, Any]] = None) -> str:
    """Resolve the YouTube transcript mode; invalid values fail back to remote_first."""
    raw, source = _setting(config, ENV_MODE, CONFIG_KEY_MODE)
    if raw is None:
        return DEFAULT_MODE
    value = raw.strip().lower()
    if value in (MODE_REMOTE_FIRST, MODE_LOCAL_ONLY):
        return value
    logger.warning("Ignoring invalid %s=%r; using %s", source, raw, DEFAULT_MODE)
    return DEFAULT_MODE


def is_local_only(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Return True when remote YouTube caption requests must not be made."""
    return resolve_mode(config) == MODE_LOCAL_ONLY


def _absolute_path(raw: str, source: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise TranscriptQueueConfigError(
            f"{source} must be an absolute path, got {raw!r}"
        )
    return path


def resolve_lt_path(config: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Return the configured absolute lt executable, or PATH's lt when unset."""
    raw, source = _setting(config, ENV_LT_PATH, CONFIG_KEY_LT_PATH)
    if raw is None:
        return shutil.which("lt")

    path = _absolute_path(raw, source or ENV_LT_PATH)
    if not path.is_file():
        raise TranscriptQueueUnavailable(
            f"{source} is not a file: {path}"
        )
    if not os.access(path, os.X_OK):
        raise TranscriptQueueUnavailable(
            f"{source} is not executable: {path}"
        )
    return str(path)


def resolve_expected_uuid(config: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    """Return an optional configured queue UUID pin."""
    raw, _ = _setting(config, ENV_QUEUE_UUID, CONFIG_KEY_QUEUE_UUID)
    return raw


def verify_queue_identity(
    queue_dir: Path,
    expected_uuid: Optional[str] = None,
) -> str:
    """Verify queue.id exists, parses, and optionally matches expected_uuid."""
    root = Path(queue_dir).expanduser()
    if not root.exists():
        raise TranscriptQueueUnavailable(f"Queue directory does not exist: {root}")
    if not root.is_dir():
        raise TranscriptQueueUnavailable(f"Queue path is not a directory: {root}")

    id_path = root / "queue.id"
    try:
        data = json.loads(id_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TranscriptQueueUnavailable(
            f"Queue identity marker missing: {id_path}"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise TranscriptQueueUnavailable(
            f"Unable to read queue identity {id_path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise TranscriptQueueUnavailable(
            f"Queue identity file {id_path} must contain a JSON object"
        )
    queue_uuid = data.get("queue_uuid")
    if not isinstance(queue_uuid, str) or not queue_uuid.strip():
        raise TranscriptQueueUnavailable(
            f"Queue identity file {id_path} has no queue_uuid"
        )
    queue_uuid = queue_uuid.strip()
    if expected_uuid and expected_uuid.strip():
        expected = expected_uuid.strip()
        if queue_uuid != expected:
            raise TranscriptQueueUnavailable(
                f"Queue UUID mismatch for {root}: found {queue_uuid!r}, "
                f"expected {expected!r}"
            )
    return queue_uuid


def resolve_queue_dir(
    config: Optional[Mapping[str, Any]] = None,
) -> Optional[Path]:
    """Return the configured absolute queue directory after identity verification."""
    raw, source = _setting(config, ENV_QUEUE_DIR, CONFIG_KEY_QUEUE_DIR)
    if raw is None:
        return None
    path = _absolute_path(raw, source or ENV_QUEUE_DIR)
    verify_queue_identity(path, expected_uuid=resolve_expected_uuid(config))
    return path
