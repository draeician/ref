"""Service layer: wrap ref_cli.cli.process_url for HTTP ingest."""

from __future__ import annotations

import contextlib
import io
import logging
import os
import threading
from typing import List

from ref_cli import cli as ref_cli
from ref_cli.youtube_extract import outbound_urls, read_video_card, youtube_video_id
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


# Bound automatic expansion of untrusted descriptions in a single API request.
# Direct input URLs retain their normal behavior; links are scanned one level.
MAX_YOUTUBE_SHOW_NOTE_LINKS = 40


def _discover_youtube_links(parent: UrlResult) -> List[str]:
    """Read show notes for a recorded YouTube video, without failing ingestion.

    Enrichment already saves a per-video JSON card during capture. Use that
    cache if available, otherwise use the existing API/yt-dlp fallback.
    Never read a transcript to discover outbound URLs.
    """
    video_id = youtube_video_id(parent.url)
    if not video_id or parent.status in {"error", "skipped"}:
        return []

    archive_base = os.path.dirname(os.path.abspath(ref_cli.UNIFIED))
    logger.info("YouTube show notes: reading video=%s url=%s", video_id, parent.url)
    try:
        card = read_video_card(video_id, archive_base)
        links = outbound_urls(card, video_id)
    except Exception as exc:  # noqa: BLE001 - link discovery is best effort
        logger.warning(
            "YouTube show notes: metadata unavailable video=%s: %s",
            video_id, exc,
        )
        return []

    description = card.get("description")
    chars = len(description) if isinstance(description, str) else 0
    logger.info(
        "YouTube show notes: video=%s source=%s description_chars=%d "
        "links_found=%d links_selected=%d",
        video_id, card.get("source", "cache"), chars, len(links),
        min(len(links), MAX_YOUTUBE_SHOW_NOTE_LINKS),
    )
    if len(links) > MAX_YOUTUBE_SHOW_NOTE_LINKS:
        logger.warning(
            "YouTube show notes: video=%s omitted %d links (limit %d)",
            video_id, len(links) - MAX_YOUTUBE_SHOW_NOTE_LINKS,
            MAX_YOUTUBE_SHOW_NOTE_LINKS,
        )
    return links[:MAX_YOUTUBE_SHOW_NOTE_LINKS]


def process_many(inputs: List[str], force: bool = False) -> List[UrlResult]:
    """Ingest inputs, then their YouTube show-note URLs through the same API path.

    Discovered URLs use process_one like explicit submissions, so skip patterns,
    deduplication, title fetching, and normal enrichment apply. Process only
    one expansion level to avoid recursive crawls and runaway processing.
    The per-URL write lock is released before scanning/processing links.
    """
    results: List[UrlResult] = []
    discovered_seen = set()
    explicit_inputs = {item.strip() for item in inputs}

    for item in inputs:
        parent = process_one(item, force=force)
        results.append(parent)

        for link in _discover_youtube_links(parent):
            if link in discovered_seen or link in explicit_inputs:
                continue
            discovered_seen.add(link)
            logger.info("YouTube show notes: processing link=%s from=%s", link, parent.url)
            child = process_one(link, force=False)
            child.discovered_from = parent.url
            results.append(child)
            logger.info(
                "YouTube show notes: result status=%s link=%s from=%s message=%s",
                child.status, link, parent.url, child.message,
            )

    return results


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
