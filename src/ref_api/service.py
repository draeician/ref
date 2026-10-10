"""Service layer: wrap ref_cli.cli.process_url for HTTP ingest."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import threading
from typing import List

from ref_cli import cli as ref_cli
from ref_api.schemas import SearchHit, TranscriptResult, UrlResult, UrlStatus

logger = logging.getLogger(__name__)
# Uvicorn often leaves the root logger at WARNING. Opt in to INFO for
# show-note discovery so journalctl includes each URL and the completion
# summary without turning on verbose logging across the whole process.
logger.setLevel(logging.INFO)

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


# Bound automatic fan-out per API request. Manual extraction has no such cap.
MAX_YOUTUBE_SHOW_NOTE_LINKS = 50


def _process_youtube_show_notes(video_url: str) -> str:
    """Record URLs in a YouTube description through the ordinary API ingest path.

    This runs after the original video's process_url call releases _write_lock.
    Child ingestion explicitly disables discovery to prevent recursive cycles.
    """
    from ref_cli.youtube_extract import (
        chapters_from_description,
        outbound_urls,
        read_video_card,
        youtube_video_id,
    )

    video_id = youtube_video_id(video_url)
    if not video_id:
        return ""

    logger.info("YouTube notes: start video_id=%s", video_id)
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
        logger.warning("YouTube notes: unavailable video_id=%s reason=%s", video_id, exc)
        return f"YouTube notes: unavailable for {video_id} ({exc})"

    logger.info(
        "YouTube notes: metadata video_id=%s source=%s description_chars=%d "
        "timestamps_ignored=%d outbound_links=%d",
        video_id, card.get("source") or "cache", len(description),
        chapter_count, len(links),
    )
    if len(links) > MAX_YOUTUBE_SHOW_NOTE_LINKS:
        logger.warning(
            "YouTube notes: capped video_id=%s found=%d limit=%d",
            video_id, len(links), MAX_YOUTUBE_SHOW_NOTE_LINKS,
        )

    counts = {"added": 0, "exists": 0, "skipped": 0, "error": 0}
    for link in links[:MAX_YOUTUBE_SHOW_NOTE_LINKS]:
        child = process_one(link, force=False, _discover_youtube_links=False)
        counts[child.status] = counts.get(child.status, 0) + 1
        if child.status == "error":
            logger.warning(
                "YouTube notes: link video_id=%s status=error url=%s reason=%s",
                video_id, link, child.message,
            )
        else:
            logger.info(
                "YouTube notes: link video_id=%s status=%s url=%s",
                video_id, child.status, link,
            )

    summary = (
        f"YouTube notes: video_id={video_id} scanned={min(len(links), MAX_YOUTUBE_SHOW_NOTE_LINKS)} "
        f"found={len(links)} timestamps_ignored={chapter_count} "
        f"added={counts['added']} exists={counts['exists']} "
        f"skipped={counts['skipped']} errors={counts['error']}"
    )
    logger.info("YouTube notes: complete %s", summary)
    return summary


def process_one(
    raw_input: str, force: bool = False, *, _discover_youtube_links: bool = True
) -> UrlResult:
    """
    Apply skip patterns, convert YouTube video IDs, then call process_url.

    Concurrent callers are serialized via a process-wide lock so appends to
    references.md do not interleave. The parent YouTube capture finishes
    before show-note child URLs are processed outside the lock.
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
        if _discover_youtube_links and status in {"added", "exists"}:
            from ref_cli.youtube_extract import youtube_video_id

            if youtube_video_id(target):
                summary = _process_youtube_show_notes(target)
                if summary:
                    output = f"{output}\n{summary}" if output else summary
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
