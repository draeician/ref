"""CLI: discover outbound links from Reddit references (ref-reddit-extract).

Reddit is a link-discovery input source, not an archive silo. This command
fetches Reddit submissions/comments (Arctic Shift archive first), extracts the
outbound URLs they point at, and reports them for the normal capture pipeline.

CLI semantics:

  - Dry-run by default: fetch + report discovered links, write nothing.
  - ``--apply``: ingest each discovered link through the normal capture path
    (``ref_cli.cli.process_url``), which writes references.md.
  - ``--no-write-refs``: never write references.md, even with ``--apply``.
    Discovered links are still printed and written to ``--out``.
  - ``--out FILE``: write discovered links to FILE (one per line), suitable for
    ``ref --file FILE``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence

from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.reddit import discover_outbound_urls, is_reddit_url
from ref_cli.references_format import iter_data_rows
from ref_cli.utils.colors import error, info, success, warning


def _default_file() -> str:
    try:
        from ref_cli.cli import UNIFIED

        return UNIFIED
    except Exception:  # noqa: BLE001
        return os.path.expanduser("~/references/references.md")


def build_arg_parser() -> argparse.ArgumentParser:
    from ref_cli import __version__

    parser = argparse.ArgumentParser(
        description=(
            "Discover outbound links from Reddit submissions/comments "
            "(Arctic Shift archive) and feed them to the normal capture path."
        ),
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="REDDIT_URL",
        help=(
            "Optional Reddit URL(s) to process. When omitted, scan references.md "
            "for Reddit rows."
        ),
    )
    file_arg = parser.add_argument(
        "--file",
        default=None,
        help="Path to references.md to scan (default: configured path)",
    )
    file_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Ingest discovered links through the normal capture path "
            "(writes references.md). Default is report-only."
        ),
    )
    parser.add_argument(
        "--no-write-refs",
        action="store_true",
        help=(
            "Never write references.md, even with --apply. Discovered links are "
            "still printed and written to --out."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write discovered outbound links to FILE (one per line)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N Reddit entries",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _collect_reddit_urls(
    targets: Sequence[str],
    refs_path: str,
    limit: Optional[int],
) -> List[str]:
    """Return Reddit URLs to process from explicit targets or references.md."""
    if targets:
        urls = [t for t in targets if is_reddit_url(t)]
    else:
        urls = []
        for row in iter_data_rows(refs_path):
            if is_reddit_url(row.url):
                urls.append(row.url)
    if limit is not None and limit > 0:
        urls = urls[:limit]
    return urls


def _run(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    enable_argcomplete(parser)
    args = parser.parse_args(argv)

    refs_path = os.path.expanduser(args.file or _default_file())
    if not args.targets and not os.path.isfile(refs_path):
        print(error(f"File not found: {refs_path}"), file=sys.stderr)
        return 1
    if args.limit is not None and args.limit < 1:
        print(error("--limit must be a positive integer"), file=sys.stderr)
        return 1

    urls = _collect_reddit_urls(args.targets, refs_path, args.limit)
    if not urls:
        print(warning("No Reddit URLs to process"), file=sys.stderr)
        return 0

    discovered: List[str] = []
    seen = set()
    for url in urls:
        print(info(f"Scanning {url}"), file=sys.stderr)
        for link in discover_outbound_urls(url):
            if link in seen:
                continue
            seen.add(link)
            discovered.append(link)
            print(info(f"  {url} -> {link}"), file=sys.stderr)

    if args.out:
        with open(os.path.expanduser(args.out), "w", encoding="utf-8") as handle:
            for link in discovered:
                handle.write(link + "\n")
        print(
            success(f"Wrote {len(discovered)} outbound link(s) to {args.out}"),
            file=sys.stderr,
        )

    if args.apply and not args.no_write_refs:
        from ref_cli.cli import process_url

        for link in discovered:
            try:
                process_url(link, force=False)
                print(success(f"Ingested {link}"), file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - one link must not abort the run
                print(error(f"Failed to ingest {link}: {exc}"), file=sys.stderr)
    elif args.apply and args.no_write_refs:
        print(
            warning(
                "--no-write-refs set: skipping references.md writes for "
                f"{len(discovered)} discovered link(s)"
            ),
            file=sys.stderr,
        )

    print(
        info(
            f"Done: {len(urls)} Reddit URL(s), {len(discovered)} outbound link(s)"
            + (" (apply)" if args.apply and not args.no_write_refs else "")
        ),
        file=sys.stderr,
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return _run(argv)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
