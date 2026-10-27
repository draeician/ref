"""Reconcile durable local-transcribe placeholders into transcript paths.

When YouTube captions are unavailable, ``ref`` records a queued placeholder in
``references.md`` and submits the video to the durable local-transcribe queue.
Once the worker completes that execution and publishes the transcript JSON into
the shared transcript directory, this module replaces the placeholder with the
transcript path.

Safety rules:

* Only rows whose ``extra`` field contains a durable-queue placeholder are
  considered. A valid transcript path is never replaced.
* The execution is looked up by its exact ID in the queue state directories;
  completed history is never enumerated.
* A completed execution must match the row's video (source key and source URL),
  carry a valid generation, and be the *current* generation in the queue key
  record. Stale or unverifiable generations are rejected.
* The transcript is read from the configured shared transcript directory, never
  from the worker-local ``output_path`` stored in the queue record.
* The archive is re-read and every target row is revalidated under the shared
  archive lock before any write. A compressed backup is written before the
  first change in a pass.
* The shared archive lock is process-local; see
  :mod:`ref_cli.archive_lock` for the single-writer API-host limitation.

The queue is owned by local-transcribe. This module only reads queue state and
never writes to it.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ref_cli import transcript_queue
from ref_cli.archive_lock import archive_lock
from ref_cli.backup_util import backup_file
from ref_cli.references_format import (
    ReferenceRow,
    format_data_line,
    parse_data_line,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_ENABLED = True
DEFAULT_INTERVAL_SECONDS = 300.0

ENV_ENABLED = "REF_TRANSCRIPT_RECONCILE_ENABLED"
CONFIG_KEY_ENABLED = "transcript_reconcile_enabled"
ENV_INTERVAL_SECONDS = "REF_TRANSCRIPT_RECONCILE_INTERVAL_SECONDS"
CONFIG_KEY_INTERVAL_SECONDS = "transcript_reconcile_interval_seconds"

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})
_FALSEY = frozenset({"0", "false", "no", "off", "disabled"})

# Placeholder text emitted by ``cli.format_queue_enqueue_message`` for the two
# durable-queue outcomes that carry an execution ID.
_PLACEHOLDER_MARKERS = (
    "queued for local-transcribe worker",
    "already in transcription queue",
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_EXECUTION_ID_RE = re.compile(
    r"\bexecution\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b",
    re.IGNORECASE,
)
_YOUTUBE_SOURCE_KEY_RE = re.compile(r"^youtube:([\w-]{11})$")

_QUEUE_STATE_DIRS = (
    "completed",
    "pending",
    "processing",
    "retry",
    "failed",
    "cancelled",
)


def _setting(
    config: Optional[Mapping[str, Any]],
    env_name: str,
    config_key: str,
) -> Tuple[Optional[str], Optional[str]]:
    raw = os.getenv(env_name)
    if raw is not None and raw.strip():
        return raw.strip(), env_name
    if config:
        value = config.get(config_key)
        if value is not None and str(value).strip():
            return str(value).strip(), config_key
    return None, None


def resolve_enabled(config: Optional[Mapping[str, Any]] = None) -> bool:
    """Return whether periodic reconciliation is enabled (default: True)."""
    raw, source = _setting(config, ENV_ENABLED, CONFIG_KEY_ENABLED)
    if raw is None:
        return DEFAULT_ENABLED
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSEY:
        return False
    logger.warning(
        "Ignoring invalid %s=%r; using enabled=%s", source, raw, DEFAULT_ENABLED
    )
    return DEFAULT_ENABLED


def resolve_interval_seconds(config: Optional[Mapping[str, Any]] = None) -> float:
    """Return the configured reconciliation interval in seconds."""
    raw, source = _setting(
        config, ENV_INTERVAL_SECONDS, CONFIG_KEY_INTERVAL_SECONDS
    )
    if raw is None:
        return DEFAULT_INTERVAL_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring invalid %s=%r; using %ss",
            source, raw, DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS
    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "Ignoring invalid %s=%r; using %ss",
            source, raw, DEFAULT_INTERVAL_SECONDS,
        )
        return DEFAULT_INTERVAL_SECONDS
    return value


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileCandidate:
    """One placeholder row and the queue execution it references."""

    line_number: int
    video_id: str
    execution_id: str
    row: ReferenceRow


@dataclass
class ReconcileResult:
    """Summary of one reconciliation pass."""

    candidates: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    backup_path: str = ""
    reasons: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.updated > 0

    def summary(self) -> str:
        text = (
            f"candidates={self.candidates} updated={self.updated} "
            f"skipped={self.skipped} errors={self.errors}"
        )
        if self.backup_path:
            text += f" backup={self.backup_path}"
        return text


# ---------------------------------------------------------------------------
# Path / queue helpers
# ---------------------------------------------------------------------------


def _expand_path(raw: Any) -> Path:
    return Path(os.path.expanduser(str(raw)))


def _cli_module():
    # Imported lazily so the module can be used with explicit paths in tests
    # without importing the full CLI (and its import-time configuration).
    from ref_cli import cli

    return cli


def resolve_archive_path(config: Optional[Mapping[str, Any]] = None) -> str:
    """Return the configured references.md path."""
    if config:
        paths = config.get("paths")
        if isinstance(paths, Mapping) and paths.get("references"):
            return str(_expand_path(paths["references"]) / "references.md")
    return _cli_module().UNIFIED


def resolve_transcripts_dir(config: Optional[Mapping[str, Any]] = None) -> Path:
    """Return the configured shared transcript directory."""
    if config:
        paths = config.get("paths")
        if isinstance(paths, Mapping) and paths.get("transcripts"):
            return _expand_path(paths["transcripts"])
    return _expand_path(_cli_module().TRANSCRIPTS_DIR)


def _resolve_queue_dir(
    config: Optional[Mapping[str, Any]],
    queue_dir: Optional[Any],
) -> Optional[Path]:
    if queue_dir is not None:
        path = _expand_path(queue_dir)
        transcript_queue.verify_queue_identity(
            path, expected_uuid=transcript_queue.resolve_expected_uuid(config)
        )
        return path
    return transcript_queue.resolve_queue_dir(config)


def _read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------


def _is_placeholder_text(text: str) -> bool:
    lower = (text or "").lower()
    return any(marker in lower for marker in _PLACEHOLDER_MARKERS)


def _execution_ids(text: str) -> List[str]:
    seen: List[str] = []
    for match in _EXECUTION_ID_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


def _video_id_from_url(url: str) -> Optional[str]:
    from ref_cli.enrichment import extract_youtube_video_id

    return extract_youtube_video_id(url)


def _candidate_from_row(row: ReferenceRow) -> Optional[ReconcileCandidate]:
    if row.source != "YouTube":
        return None
    if not _is_placeholder_text(row.extra):
        return None
    ids = _execution_ids(row.extra)
    if len(ids) != 1:
        logger.warning(
            "Transcript reconciliation: skipping row %s with %d execution IDs",
            row.line_number, len(ids),
        )
        return None
    video_id = _video_id_from_url(row.url)
    if not video_id:
        logger.warning(
            "Transcript reconciliation: skipping row %s with no YouTube video ID",
            row.line_number,
        )
        return None
    return ReconcileCandidate(
        line_number=row.line_number,
        video_id=video_id,
        execution_id=ids[0],
        row=row,
    )


def _scan_candidates(archive_path: str) -> List[ReconcileCandidate]:
    candidates: List[ReconcileCandidate] = []
    with open(archive_path, "r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            # Cheap prefilter: most of the archive is not a queue placeholder.
            if not _is_placeholder_text(line):
                continue
            row = parse_data_line(line, line_number=line_number)
            if row is None:
                continue
            candidate = _candidate_from_row(row)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


# ---------------------------------------------------------------------------
# Queue / transcript validation
# ---------------------------------------------------------------------------


def _valid_generation(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _find_execution(
    queue_dir: Path,
    execution_id: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not _UUID_RE.match(execution_id or ""):
        return None, "invalid execution ID"

    for state in _QUEUE_STATE_DIRS:
        path = queue_dir / state / f"{execution_id}.json"
        if not path.is_file():
            continue
        try:
            record = _read_json(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"malformed {state} execution record: {exc}"
        if not isinstance(record, dict):
            return None, f"{state} execution record is not a JSON object"
        if record.get("execution_id") != execution_id:
            return None, f"{state} execution ID does not match queue filename"
        if state != "completed":
            return None, f"execution is {state}"
        return record, ""

    return None, "execution not found in queue"


def _load_key_record(
    queue_dir: Path,
    source_key: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if not _YOUTUBE_SOURCE_KEY_RE.match(source_key or ""):
        return None, "invalid queue source key"
    key_name = source_key.replace(":", "__") + ".json"
    path = queue_dir / "keys" / key_name
    if not path.is_file():
        return None, "queue key record missing"
    try:
        record = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"malformed queue key record: {exc}"
    if not isinstance(record, dict):
        return None, "queue key record is not a JSON object"
    if record.get("source_key") != source_key:
        return None, "queue key record source does not match execution"
    return record, ""


def _validate_execution(
    record: Dict[str, Any],
    *,
    execution_id: str,
    video_id: str,
    queue_dir: Path,
) -> str:
    if record.get("status") != "completed":
        return f"execution status is {record.get('status')!r}, not completed"

    source_key = record.get("source_key")
    expected_key = f"youtube:{video_id}"
    if source_key != expected_key:
        return "execution belongs to a different video"

    source_type = record.get("source_type")
    if source_type is not None and source_type != "youtube":
        return f"execution source type is {source_type!r}, not youtube"

    source_url = record.get("source")
    if not isinstance(source_url, str) or _video_id_from_url(source_url) != video_id:
        return "execution source URL does not match the row video"

    if record.get("error") not in (None, ""):
        return "completed execution contains an error"

    generation = record.get("generation")
    if not _valid_generation(generation):
        return "execution generation is missing or invalid"

    key_record, reason = _load_key_record(queue_dir, source_key)
    if key_record is None:
        return reason

    key_generation = key_record.get("generation")
    if not _valid_generation(key_generation):
        return "queue key generation is missing or invalid"
    if key_generation != generation:
        return (
            f"generation conflict (execution {generation}, key {key_generation})"
        )
    if key_record.get("current_execution_id") != execution_id:
        return "execution is not the current queue generation"

    return ""


def _validate_transcript(
    transcripts_dir: Path,
    video_id: str,
) -> Tuple[Optional[str], str]:
    path = transcripts_dir / f"{video_id}.json"
    if not path.is_file():
        return None, "transcript file missing"
    try:
        data = _read_json(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"malformed transcript JSON: {exc}"
    if not isinstance(data, dict):
        return None, "transcript JSON is not an object"

    text = data.get("transcript")
    if not isinstance(text, str) or not text.strip():
        return None, "transcript text is empty"

    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        return None, "transcript metadata is missing"
    if metadata.get("id") != video_id:
        return None, "transcript metadata video ID does not match"

    return str(path), ""


def _resolve_candidate(
    candidate: ReconcileCandidate,
    *,
    queue_dir: Path,
    transcripts_dir: Path,
) -> Tuple[Optional[str], str]:
    record, reason = _find_execution(queue_dir, candidate.execution_id)
    if record is None:
        return None, reason

    reason = _validate_execution(
        record,
        execution_id=candidate.execution_id,
        video_id=candidate.video_id,
        queue_dir=queue_dir,
    )
    if reason:
        return None, reason

    return _validate_transcript(transcripts_dir, candidate.video_id)


def _replace_placeholder_field(extra: str, transcript_path: str) -> Optional[str]:
    """Replace only the placeholder field, preserving other ``extra`` fields."""
    parts = (extra or "").split("|")
    replaced = False
    new_parts: List[str] = []
    for part in parts:
        if _is_placeholder_text(part):
            new_parts.append(transcript_path)
            replaced = True
        else:
            new_parts.append(part)
    return "|".join(new_parts) if replaced else None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile_transcripts(
    *,
    archive_path: Optional[str] = None,
    config: Optional[Mapping[str, Any]] = None,
    transcripts_dir: Optional[Any] = None,
    queue_dir: Optional[Any] = None,
) -> ReconcileResult:
    """Run one reconciliation pass.

    This never raises for missing NFS mounts, malformed queue records, or
    temporary I/O errors; those are reported in the returned result and logged.
    Programming errors in the archive write path are also contained so the API
    worker stays alive.
    """
    result = ReconcileResult()
    config = config or {}
    archive_path = archive_path or resolve_archive_path(config)
    transcripts_path = (
        _expand_path(transcripts_dir)
        if transcripts_dir is not None
        else resolve_transcripts_dir(config)
    )

    if not os.path.isfile(archive_path):
        result.reasons.append(f"archive not found: {archive_path}")
        logger.warning("Transcript reconciliation skipped: %s", result.reasons[-1])
        return result

    try:
        resolved_queue = _resolve_queue_dir(config, queue_dir)
    except transcript_queue.TranscriptQueueConfigError as exc:
        result.reasons.append(f"queue unavailable: {exc}")
        logger.warning("Transcript reconciliation skipped: %s", result.reasons[-1])
        return result

    if resolved_queue is None:
        result.reasons.append("durable queue is not configured")
        logger.debug("Transcript reconciliation skipped: %s", result.reasons[-1])
        return result

    try:
        candidates = _scan_candidates(archive_path)
    except OSError as exc:
        result.errors += 1
        result.reasons.append(f"unable to read archive: {exc}")
        logger.warning("Transcript reconciliation skipped: %s", result.reasons[-1])
        return result

    result.candidates = len(candidates)
    if not candidates:
        return result

    candidate_keys: Set[Tuple[str, str]] = {
        (candidate.video_id, candidate.execution_id) for candidate in candidates
    }
    validated: Dict[Tuple[str, str], Tuple[Optional[str], str]] = {}

    try:
        # The read/decide/write commit is one critical section under the shared
        # archive lock. Rows are re-parsed and revalidated here so a concurrent
        # capture or enrichment update cannot be overwritten with a stale view.
        with archive_lock:
            with open(
                archive_path, "r", encoding="utf-8", errors="replace"
            ) as handle:
                lines = handle.readlines()

            new_lines: List[str] = []
            updates = 0
            for line_number, line in enumerate(lines, start=1):
                row = parse_data_line(line, line_number=line_number)
                if row is None:
                    new_lines.append(line)
                    continue

                candidate = _candidate_from_row(row)
                if candidate is None or (
                    candidate.video_id, candidate.execution_id
                ) not in candidate_keys:
                    new_lines.append(line)
                    continue

                key = (candidate.video_id, candidate.execution_id)
                if key not in validated:
                    validated[key] = _resolve_candidate(
                        candidate,
                        queue_dir=resolved_queue,
                        transcripts_dir=transcripts_path,
                    )
                transcript_path, reason = validated[key]
                if transcript_path is None:
                    result.skipped += 1
                    result.reasons.append(
                        f"{candidate.video_id}: {reason}"
                    )
                    logger.info(
                        "Transcript reconciliation: skipped video_id=%s "
                        "execution=%s reason=%s",
                        candidate.video_id, candidate.execution_id, reason,
                    )
                    new_lines.append(line)
                    continue

                new_extra = _replace_placeholder_field(
                    row.extra, transcript_path
                )
                if new_extra is None:
                    result.skipped += 1
                    result.reasons.append(
                        f"{candidate.video_id}: placeholder field not found"
                    )
                    new_lines.append(line)
                    continue

                new_line = format_data_line(replace(row, extra=new_extra)) + "\n"
                if new_line == line:
                    result.skipped += 1
                    new_lines.append(line)
                    continue

                new_lines.append(new_line)
                updates += 1

            if updates:
                try:
                    result.backup_path = backup_file(
                        archive_path, compress=True, style="suffix"
                    )
                except OSError as exc:
                    result.errors += updates
                    result.reasons.append(f"backup failed: {exc}")
                    logger.error(
                        "Transcript reconciliation: refusing to rewrite archive "
                        "without a backup: %s", exc,
                    )
                    return result

                try:
                    with open(archive_path, "w", encoding="utf-8") as handle:
                        handle.writelines(new_lines)
                except OSError as exc:
                    result.errors += updates
                    result.reasons.append(f"archive write failed: {exc}")
                    logger.error(
                        "Transcript reconciliation: archive write failed: %s",
                        exc,
                    )
                    return result

                result.updated = updates
                logger.info(
                    "Transcript reconciliation: updated=%d backup=%s",
                    updates, result.backup_path,
                )
    except OSError as exc:
        result.errors += 1
        result.reasons.append(f"archive reconciliation failed: {exc}")
        logger.warning("Transcript reconciliation failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - worker must survive unexpected errors
        result.errors += 1
        result.reasons.append(f"unexpected reconciliation error: {exc}")
        logger.exception("Transcript reconciliation raised an unexpected error")

    return result
