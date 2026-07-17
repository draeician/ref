"""CLI: enrich references.md with source categories + meta cards.

YouTube first (API or yt-dlp). Writes:

- Thin ``@meta|category|role|channel_id`` on matching references.md rows
- Full cards under ``enrichment/youtube/videos|channels/*.json``
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.enrichment import (
    append_index,
    ensure_enrichment_dirs,
    extract_youtube_video_id,
    fetch_youtube_video,
    load_video_card,
    save_video_card,
    update_channel_card,
    video_card_path,
)
from ref_cli.references_format import (
    REFERENCES_FORMAT_VERSION,
    ReferenceRow,
    apply_row_updates,
    ensure_references_migrated,
    iter_data_rows,
    with_meta,
)
from ref_cli.utils.colors import dim, error, info, success, warning

# Default batch size for interactive runs. Large enough to make progress on a
# big archive, small enough to be polite to YouTube / yt-dlp and easy to Ctrl+C.
# Override with --limit N, or --limit 0 for no cap.
DEFAULT_ENRICH_LIMIT = 50


def _default_paths() -> Tuple[str, str]:
    """Return (references.md path, references base dir)."""
    try:
        from ref_cli.cli import BASE, UNIFIED
        return UNIFIED, BASE
    except Exception:  # noqa: BLE001
        base = os.path.expanduser('~/references')
        return os.path.join(base, 'references.md'), base


def build_arg_parser() -> argparse.ArgumentParser:
    from ref_cli import __version__

    parser = argparse.ArgumentParser(
        description=(
            'Enrich references.md with source categories and store full meta '
            'cards under enrichment/<platform>/ (YouTube supported now).'
        ),
    )
    file_arg = parser.add_argument(
        '--file',
        default=None,
        help='Path to references.md (default: configured path)',
    )
    file_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        '--platform',
        choices=('youtube',),
        default='youtube',
        help='Platform to enrich (default: youtube; more later)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=DEFAULT_ENRICH_LIMIT,
        help=(
            f'Max videos to fetch this run (default: {DEFAULT_ENRICH_LIMIT}; '
            'use 0 for no cap)'
        ),
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Re-fetch even when a video card / @meta already exists',
    )
    parser.add_argument(
        '--skip-existing-cards',
        action='store_true',
        help='Skip when enrichment/youtube/videos/<id>.json exists (default behavior unless --force)',
    )
    parser.add_argument(
        '--no-write-refs',
        action='store_true',
        help='Only write meta cards; do not update references.md rows',
    )
    parser.add_argument(
        '--no-migrate',
        action='store_true',
        help='Do not auto-migrate references.md header to current version',
    )
    parser.add_argument(
        '--nocompress',
        action='store_true',
        help='Write plain (uncompressed) migrate backups instead of .gz',
    )
    parser.add_argument(
        '--prefer-ytdlp',
        action='store_true',
        help='Use yt-dlp first instead of YouTube Data API',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Resolve work list and print actions without fetching/writing',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    return parser


def _youtube_api_key() -> Optional[str]:
    return os.environ.get('YOUTUBE_API_KEY') or None


def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    enable_argcomplete(parser)
    args = parser.parse_args(argv)

    default_file, default_base = _default_paths()
    refs_path = os.path.expanduser(args.file or default_file)
    base = os.path.dirname(os.path.abspath(refs_path)) or default_base

    if not os.path.isfile(refs_path):
        print(error(f'File not found: {refs_path}'), file=sys.stderr)
        return 1
    if args.limit < 0:
        print(error('--limit must be >= 0 (0 = no cap)'), file=sys.stderr)
        return 1
    limit: Optional[int] = None if args.limit == 0 else args.limit

    if not args.no_migrate:
        msg = ensure_references_migrated(
            refs_path,
            backup=True,
            compress=not args.nocompress,
        )
        if msg:
            print(info(msg), file=sys.stderr)

    paths = ensure_enrichment_dirs(base, args.platform)
    print(info(f'Enrichment dirs ready under {paths["root"]}'), file=sys.stderr)
    print(dim(f'references: {refs_path}'), file=sys.stderr)

    api_key = _youtube_api_key()
    if api_key and not args.prefer_ytdlp:
        print(dim('fetch backend: YouTube Data API (fallback yt-dlp)'), file=sys.stderr)
    else:
        print(dim('fetch backend: yt-dlp'), file=sys.stderr)

    # Build work list: one job per unique video_id, track all rows to stamp.
    rows_by_video: dict = {}
    for row in iter_data_rows(refs_path):
        if args.platform == 'youtube':
            vid = extract_youtube_video_id(row.url)
            if not vid:
                continue
            rows_by_video.setdefault(vid, []).append(row)

    work_ids: List[str] = []
    for vid, rows in rows_by_video.items():
        if not args.force:
            card_exists = os.path.isfile(video_card_path(base, vid))
            all_have_meta = all(r.has_meta for r in rows)
            if card_exists and all_have_meta:
                continue
            if card_exists and args.skip_existing_cards:
                # Still may need to stamp @meta from card
                if all_have_meta:
                    continue
        work_ids.append(vid)

    if limit is not None:
        work_ids = work_ids[:limit]

    print(
        info(
            f'YouTube videos in file: {len(rows_by_video)}; '
            f'to process: {len(work_ids)}'
            + (f' (limit={limit})' if limit is not None else ' (no limit)')
        ),
        file=sys.stderr,
    )

    if args.dry_run:
        for vid in work_ids[:50]:
            print(f'  would enrich {vid} ({len(rows_by_video[vid])} row(s))')
        if len(work_ids) > 50:
            print(dim(f'  … and {len(work_ids) - 50} more'))
        return 0

    fetched = 0
    reused = 0
    failed = 0
    updates: List[Tuple[int, ReferenceRow]] = []

    for i, vid in enumerate(work_ids, start=1):
        print(info(f'[{i}/{len(work_ids)}] {vid}'), file=sys.stderr)
        card = None if args.force else load_video_card(base, vid)
        enrichment = None

        if card and not args.force:
            reused += 1
            category = card.get('category') or ''
            role = card.get('role') or ''
            channel_id = card.get('channel_id') or ''
            print(dim(f'  reuse card → {category or "?"} / {role or "?"}'), file=sys.stderr)
        else:
            try:
                enrichment = fetch_youtube_video(
                    vid,
                    api_key=api_key,
                    prefer_api=not args.prefer_ytdlp,
                )
                save_video_card(base, enrichment)
                update_channel_card(base, enrichment)
                append_index(
                    base,
                    platform='youtube',
                    key=vid,
                    status='ok',
                    detail=f'{enrichment.category}|{enrichment.role}',
                )
                category = enrichment.category
                role = enrichment.role
                channel_id = enrichment.channel_id
                fetched += 1
                print(
                    success(
                        f'  {enrichment.source}: {category or "?"} / {role} '
                        f'ch={channel_id or "-"}'
                    ),
                    file=sys.stderr,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                append_index(
                    base,
                    platform='youtube',
                    key=vid,
                    status='error',
                    detail=str(exc)[:200],
                )
                print(error(f'  failed: {exc}'), file=sys.stderr)
                continue

        if args.no_write_refs:
            continue

        for row in rows_by_video[vid]:
            if row.has_meta and not args.force:
                continue
            updated = with_meta(
                row,
                category=category,
                role=role,
                channel_id=channel_id,
            )
            updates.append((row.line_number, updated))

    if updates and not args.no_write_refs:
        n = apply_row_updates(refs_path, updates, backup=False)
        print(success(f'Updated {n} references.md row(s) with @meta'), file=sys.stderr)
    elif not args.no_write_refs:
        print(dim('No references.md row updates needed'), file=sys.stderr)

    print(
        info(
            f'Done: fetched={fetched} reused_cards={reused} failed={failed} '
            f'(format v{REFERENCES_FORMAT_VERSION})'
        ),
        file=sys.stderr,
    )
    return 1 if failed and not fetched and not reused else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        try:
            print(file=sys.stderr)
            print(warning('Interrupted.'), file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        return 130
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
