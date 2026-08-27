"""Service layer: wrap ref_cli.cli.process_url for HTTP ingest."""

from __future__ import annotations

import contextlib
import io
import logging
import threading
from typing import List

from ref_cli import cli as ref_cli
from ref_api.schemas import SearchHit, TranscriptResult, UrlResult, UrlStatus

logger = logging.getLogger(__name__)

# Serialize writes to references.md across concurrent requests.
_write_lock = threading.Lock()


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


def process_one(raw_input: str, force: bool = False) -> UrlResult:
    """
    Apply skip patterns, convert YouTube video IDs, then call process_url.

    Concurrent callers are serialized via a process-wide lock so appends to
    references.md do not interleave.
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
        with _write_lock:
            with contextlib.redirect_stdout(buf):
                ref_cli.process_url(target, force)
        output = buf.getvalue().strip()
        status = _classify_stdout(output)
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
        with _write_lock:
            with contextlib.redirect_stdout(buf):
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
