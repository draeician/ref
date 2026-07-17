"""Shared helpers for repairing titles in references.md in place."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from ref_cli.cli import UNIFIED, get_title_from_url
from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.utils.colors import dim, error, info, success, warning

UrlPredicate = Callable[[str], bool]
TitleFetcher = Callable[[str], str]

_URL_FIELD_RE = re.compile(r'^\[(.*)\]$')
_TITLE_FIELD_RE = re.compile(r'^\((.*)\)$', re.DOTALL)


@dataclass
class RepairStats:
    matched: int = 0
    ok: int = 0
    would_update: int = 0
    updated: int = 0
    failed: int = 0
    skipped: int = 0
    changes: List[Tuple[int, str, str, str]] = field(default_factory=list)


def extract_url(url_field: str) -> Optional[str]:
    """Extract the URL from a ``[url]`` field, tolerating a leading underscore."""
    if url_field is None:
        return None
    raw = url_field.strip()
    match = _URL_FIELD_RE.match(raw)
    if not match:
        return None
    url = match.group(1).strip()
    if url.startswith('_'):
        url = url[1:]
    return url or None


def extract_title(title_field: str) -> str:
    """Extract the title from a ``(title)`` field, or return the raw field."""
    if title_field is None:
        return ''
    raw = title_field.strip()
    match = _TITLE_FIELD_RE.match(raw)
    if match:
        return match.group(1)
    return raw


def replace_title(line: str, new_title: str) -> str:
    """Return ``line`` with only the title field replaced by ``(new_title)``."""
    newline = '\n' if line.endswith('\n') else ''
    parts = line.rstrip('\n').split('|')
    if len(parts) < 5:
        raise ValueError('line does not have the expected number of fields')
    parts[2] = f'({new_title})'
    return '|'.join(parts) + newline


def is_usable_title(title: Optional[str]) -> bool:
    """Return True when a fetched title is safe to write into references.md."""
    if not title:
        return False
    cleaned = title.strip()
    if not cleaned:
        return False
    if cleaned == 'No title found':
        return False
    if cleaned.startswith('Error:'):
        return False
    return True


def parse_entry_line(line: str) -> Optional[Tuple[str, str, Sequence[str]]]:
    """Parse a references.md data line into ``(url, stored_title, parts)``."""
    stripped = line.rstrip('\n')
    if not stripped or stripped.startswith('Date|'):
        return None
    parts = stripped.split('|')
    if len(parts) < 5:
        return None
    url = extract_url(parts[1])
    if not url:
        return None
    return url, extract_title(parts[2]), parts


def iter_matching_entries(
    path: str,
    url_predicate: UrlPredicate,
) -> Iterable[Tuple[int, str, str, str]]:
    """Yield ``(line_number, line, url, stored_title)`` for matching hosts."""
    with open(path, 'r', encoding='utf-8') as handle:
        for line_number, line in enumerate(handle, start=1):
            parsed = parse_entry_line(line)
            if not parsed:
                continue
            url, stored_title, _parts = parsed
            if url_predicate(url):
                yield line_number, line, url, stored_title


def repair_titles(
    path: str,
    url_predicate: UrlPredicate,
    *,
    apply: bool = False,
    limit: Optional[int] = None,
    fetch_title: Optional[TitleFetcher] = None,
) -> RepairStats:
    """Scan ``path``, compare titles, and optionally rewrite mismatches in place.

    Line order and all non-title fields are preserved. Failed fetches leave the
    existing title unchanged.
    """
    if fetch_title is None:
        fetch_title = get_title_from_url
    stats = RepairStats()
    with open(path, 'r', encoding='utf-8') as handle:
        lines = handle.readlines()

    processed = 0
    for index, line in enumerate(lines):
        if limit is not None and processed >= limit:
            break
        parsed = parse_entry_line(line)
        if not parsed:
            continue
        url, stored_title, _parts = parsed
        if not url_predicate(url):
            continue

        stats.matched += 1
        processed += 1
        print(info(f"[{processed}] Checking {url}"))

        try:
            fetched = fetch_title(url)
        except Exception as exc:  # noqa: BLE001 - report and continue
            stats.failed += 1
            print(error(f"  fetch error: {exc}"))
            continue

        if not is_usable_title(fetched):
            stats.failed += 1
            print(warning(f"  unusable title ({fetched!r}); leaving stored title alone"))
            continue

        fetched = fetched.strip()
        if fetched == stored_title:
            stats.ok += 1
            print(success("  ok"))
            continue

        stats.changes.append((index + 1, url, stored_title, fetched))
        if apply:
            lines[index] = replace_title(line, fetched)
            stats.updated += 1
            print(success(f"  updated: {dim(stored_title)} -> {fetched}"))
        else:
            stats.would_update += 1
            print(warning(f"  would update: {dim(stored_title)} -> {fetched}"))

    if apply and stats.updated:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.writelines(lines)

    return stats


def print_summary(stats: RepairStats, *, apply: bool) -> None:
    """Print a short repair summary."""
    mode = 'apply' if apply else 'dry-run'
    print()
    print(info(f"Summary ({mode}):"))
    print(f"  matched:       {stats.matched}")
    print(f"  ok:            {stats.ok}")
    if apply:
        print(f"  updated:       {stats.updated}")
    else:
        print(f"  would update:  {stats.would_update}")
    print(f"  failed/skip:   {stats.failed + stats.skipped}")


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """Build the shared CLI argument parser for title repair tools."""
    from ref_cli import __version__

    parser = argparse.ArgumentParser(description=description)
    file_arg = parser.add_argument(
        '--file',
        default=UNIFIED,
        help=f'Path to references.md (default: {UNIFIED})',
    )
    file_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Write title updates in place (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Process at most N matching entries',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    return parser


def run_repair_cli(
    description: str,
    url_predicate: UrlPredicate,
    argv: Optional[Sequence[str]] = None,
) -> int:
    """Parse args and run a title repair pass. Returns a process exit code."""
    parser = build_arg_parser(description)
    # Shell tab completion (no-op unless _ARGCOMPLETE is set by the shell)
    enable_argcomplete(parser)
    args = parser.parse_args(argv)
    path = os.path.expanduser(args.file)
    if not os.path.isfile(path):
        print(error(f"File not found: {path}"))
        return 1
    if args.limit is not None and args.limit < 1:
        print(error('--limit must be a positive integer'))
        return 1

    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(info(f"{description} [{mode}]"))
    print(dim(f"file: {path}"))
    stats = repair_titles(
        path,
        url_predicate,
        apply=args.apply,
        limit=args.limit,
    )
    print_summary(stats, apply=args.apply)
    return 0
