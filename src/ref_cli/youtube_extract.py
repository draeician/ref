"""Discover links in YouTube show notes and ingest them through ref-api.

Uses existing YouTube enrichment cards when available; otherwise fetches video
metadata through the same YouTube API / yt-dlp fallback used by ref-enrich.
Reading is non-destructive. Only --apply submits URLs to ref-api /urls.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlsplit

from ref_cli.api_client import ApiError, get_api_base_url, ingest_urls
from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.enrichment import (
    extract_urls,
    extract_youtube_video_id,
    fetch_youtube_video,
    load_video_card,
    save_video_card,
)
from ref_cli.references_format import iter_data_rows


_CHAPTER_RE = re.compile(
    r"^\s*(?:\[)?(?P<time>\d{1,2}:\d{2}(?::\d{2})?)(?:\])?"
    r"\s*(?:[-|:]\s*)?(?P<title>\S.*)$"
)


def youtube_video_id(url: str) -> Optional[str]:
    """Accept only actual YouTube video URLs, not lookalike hostnames."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not (
        host == "youtu.be"
        or host.endswith(".youtu.be")
        or host == "youtube.com"
        or host.endswith(".youtube.com")
    ):
        return None
    return extract_youtube_video_id(url)


def is_youtube_playlist_url(url: str) -> bool:
    """True when ``url`` is a YouTube playlist link that would trigger full
    playlist ingestion (a ``list=`` query parameter that is not a radio/mix).

    Used by the API service to distinguish a *discovered* show-note child that is
    a playlist (which must be recorded as a link without expanding its videos)
    from an ordinary video or a directly submitted playlist.
    """
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not (
        host == "youtube.com" or host.endswith(".youtube.com")
    ):
        return False
    query = parse_qs(parsed.query)
    list_ids = query.get("list") or []
    if not list_ids:
        return False
    if "start_radio" in query:
        return False
    if str(list_ids[0]).startswith("RD"):
        return False
    return True


def _safe_link(link: str) -> bool:
    """Don't send local/private URL targets from untrusted descriptions to API.

    The archive server should also enforce its own network access policy:
    client-side checks cannot prevent redirects or DNS rebinding.
    """
    # Discovered URLs are untrusted. Legacy ref title extraction launches
    # lynx via a shell; reject unsafe literal characters before forwarding.
    # Percent-encoded query strings remain usable.
    if any(ord(char) < 32 or char in '"\'\\\\\x60$|' for char in link):
        return False
    try:
        parsed = urlsplit(link)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.port is not None and parsed.port <= 0:
            return False
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if "." not in host and ":" not in host:
        return False
    if host.endswith((".local", ".localhost", ".internal", ".test", ".invalid", ".home.arpa")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def chapters_from_description(description: str) -> List[Tuple[str, str]]:
    """Find timestamps and their headings in video show notes."""
    chapters: List[Tuple[str, str]] = []
    for line in (description or "").splitlines():
        match = _CHAPTER_RE.match(line)
        if match:
            chapters.append((match.group("time"), match.group("title").strip()))
    return chapters


def outbound_urls(card: Dict[str, object], video_id: str) -> List[str]:
    """Read description and previously extracted card links in original order."""
    description = card.get("description") or ""
    candidates = extract_urls(description if isinstance(description, str) else "")
    stored_links = card.get("links") or {}
    if isinstance(stored_links, dict):
        for values in stored_links.values():
            if isinstance(values, list):
                candidates.extend(item for item in values if isinstance(item, str))

    # HTTP and HTTPS variants with the same host/path/query/fragment are
    # usually the same referenced resource. Prefer HTTPS when both appear,
    # retaining the original first-seen position.
    positions: Dict[Tuple[str, str, str, str, str], int] = {}
    result: List[str] = []
    for link in candidates:
        if not _safe_link(link):
            continue
        if youtube_video_id(link) == video_id:  # Don't re-submit this video.
            continue
        parsed = urlsplit(link)
        key = (
            (parsed.hostname or "").lower(),
            str(parsed.port or ""),
            parsed.path or "/",
            parsed.query,
            parsed.fragment,
        )
        if key in positions:
            previous = positions[key]
            if parsed.scheme == "https" and result[previous].startswith("http://"):
                result[previous] = link
            continue
        positions[key] = len(result)
        result.append(link)
    return result


def read_video_card(video_id: str, references_base: str, *, refresh: bool = False) -> Dict[str, object]:
    """Use cached enrichment first and fetch/save metadata on cache miss."""
    card = None if refresh else load_video_card(references_base, video_id)
    if card is None:
        video = fetch_youtube_video(video_id, api_key=os.environ.get("YOUTUBE_API_KEY"))
        save_video_card(references_base, video)
        card = video.to_card()
    if card.get("source") == "unavailable" or card.get("role") == "unavailable":
        raise ValueError("video metadata unavailable")
    return card


def _default_file() -> str:
    from ref_cli.cli import UNIFIED

    return UNIFIED


def _source_urls(targets: Sequence[str], refs_file: str, limit: Optional[int]) -> List[str]:
    if targets:
        urls = list(targets)
    else:
        urls = [row.url for row in iter_data_rows(refs_file)]
    found: List[str] = []
    seen = set()
    for url in urls:
        video_id = youtube_video_id(url)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        found.append(url)
        if limit is not None and len(found) >= limit:
            break
    return found


def build_arg_parser() -> argparse.ArgumentParser:
    from ref_cli import __version__

    parser = argparse.ArgumentParser(
        description="Read YouTube video show notes and discover referenced URLs."
    )
    parser.add_argument(
        "targets", nargs="*", metavar="YOUTUBE_URL",
        help="YouTube video URL(s). Without targets, scan references.md.",
    )
    file_arg = parser.add_argument(
        "--file", help="references.md to scan (default: configured archive)"
    )
    file_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        "--apply", action="store_true",
        help="Record videos and discovered links via ref-api POST /urls (requires api_url).",
    )
    parser.add_argument("--out", help="Write discovered URLs to this file")
    parser.add_argument("--limit", type=int, help="Process at most N videos")
    parser.add_argument(
        "--refresh", action="store_true", help="Re-fetch metadata even if card is cached"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _submit(base_url: str, link: str) -> bool:
    """Return True for successful API ingestion (including already present)."""
    try:
        results = ingest_urls(base_url, url_value=link)
    except ApiError as exc:
        print(f"API error for {link}: {exc}", file=sys.stderr)
        return False
    if len(results) != 1 or results[0].get("status") not in {"added", "exists", "skipped"}:
        detail = results[0].get("message") if results else "invalid API response"
        print(f"API failed for {link}: {detail}", file=sys.stderr)
        return False
    print(f"API {results[0]['status']}: {link}", file=sys.stderr)
    return True


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    enable_argcomplete(parser)
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    refs_file = os.path.expanduser(args.file or _default_file())
    if not args.targets and not os.path.isfile(refs_file):
        print(f"File not found: {refs_file}", file=sys.stderr)
        return 1

    base_url = None
    if args.apply:
        from ref_cli.cli import load_config

        base_url = get_api_base_url(load_config())
        if not base_url:
            print("--apply requires api_url or REF_API_URL to send links through ref-api", file=sys.stderr)
            return 1

    urls = _source_urls(args.targets, refs_file, args.limit)
    if not urls:
        print("No YouTube video URLs found", file=sys.stderr)
        return 1 if args.targets else 0

    references_base = os.path.dirname(os.path.abspath(refs_file))
    discovered: List[str] = []
    seen_links = set()
    submitted = set()
    failed = False
    for url in urls:
        video_id = youtube_video_id(url)
        if video_id is None:
            continue
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        if base_url and canonical_url not in submitted:
            submitted.add(canonical_url)
            failed = not _submit(base_url, canonical_url) or failed
        try:
            card = read_video_card(video_id, references_base, refresh=args.refresh)
        except Exception as exc:  # noqa: BLE001 - one video should not stop the scan
            print(f"Could not read YouTube notes for {url}: {exc}", file=sys.stderr)
            failed = True
            continue

        print(f"\nVideo: {card.get('title') or video_id}")
        print(f"URL: https://www.youtube.com/watch?v={video_id}")
        print(f"Channel: {card.get('channel_title') or 'unknown'}")
        print(f"Published: {card.get('published_at') or 'unknown'}")
        print(f"Category: {card.get('category') or 'unknown'}")
        if card.get("duration_sec") is not None:
            print(f"Duration (seconds): {card['duration_sec']}")
        tags = card.get("tags") or []
        if isinstance(tags, list) and tags:
            print("Tags: " + ", ".join(str(tag) for tag in tags))
        description = card.get("description") or ""
        print("Show notes:\n" + (description if isinstance(description, str) and description else "(none)"))
        chapters = chapters_from_description(description if isinstance(description, str) else "")
        if chapters:
            print("Chapters:")
            for timestamp, label in chapters:
                print(f"  {timestamp} {label}")

        links = outbound_urls(card, video_id)
        print(f"Discovered links ({len(links)}):")
        for link in links:
            print(f"  {link}")
            if link not in seen_links:
                seen_links.add(link)
                discovered.append(link)

        if base_url:
            for target in links:
                if target not in submitted:
                    submitted.add(target)
                    failed = not _submit(base_url, target) or failed

    if args.out:
        with open(os.path.expanduser(args.out), "w", encoding="utf-8") as handle:
            for link in discovered:
                handle.write(link + "\n")
        print(f"Wrote {len(discovered)} link(s) to {args.out}", file=sys.stderr)

    print(
        f"Scanned {len(urls)} YouTube video(s); found {len(discovered)} distinct link(s)"
        + ("; sent to ref-api" if base_url else "; dry run"),
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
