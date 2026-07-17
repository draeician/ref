"""Versioned references.md format: header, parse/serialize, migrate.

Schema (version 2)
------------------
Header comments (``# …``) then data lines::

    timestamp|[url]|(title)|uploader|source[|extra…][|@meta|category|role|channel_id]

- ``extra`` is optional (transcript path/status; may be multiple legacy fields).
- ``@meta`` is a sentinel so category/role/channel_id are unambiguous even when
  titles/uploaders contain ``|``.
- Full enrichment cards live under ``enrichment/<platform>/`` (see enrichment.py).

Format upgrades
---------------
Upgrades are **layered**: each step transforms the file from version N → N+1.
Migrating an ancient file runs every step in order (1→2→3→…→current).

Register new steps in :data:`MIGRATION_STEPS` only. Do not rewrite history of
older steps — someone may still open a pre-header capture years from now.

Version map:
  * **1** — original capture format (no ``# ref-references`` header; may start
    with a legacy ``Date|URL|Title|…`` line). This is the implicit version when
    no header is present.
  * **2** — version header + optional trailing ``@meta|category|role|channel_id``;
    enrichment cards live beside the file under ``enrichment/``.
  * **3+** — add a ``_migrate_N_to_N+1`` function and append it to
    ``MIGRATION_STEPS`` (see comments on that list).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Current on-disk contract
# ---------------------------------------------------------------------------

# Bump when the on-disk row/header contract changes — and add a migration step.
REFERENCES_FORMAT_VERSION = 2

# Files with no version header are treated as this version (pre-header captures).
LEGACY_UNVERSIONED = 1

HEADER_PREFIX = '# ref-references version='
META_SENTINEL = '@meta'

_LINE_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
    r'\|\[(?P<url>[^\]]+)\]'
    r'\|\((?P<title>.*)\)\|'
    r'(?P<rest>.*)$'
)

_SOURCE_MARKERS = frozenset({'YouTube', 'General', 'Rumble'})

# Legacy first-line header seen in older captures (not a data row).
_LEGACY_HEADER_RE = re.compile(
    r'^Date\|URL\|Title\|',
    re.IGNORECASE,
)

# Comment keys rewritten each successful migrate (not data).
_MANAGED_HEADER_PREFIXES = (
    HEADER_PREFIX,
    '# format:',
    '# enrichment:',
    '# migrated:',
    '# migration-path:',
)


@dataclass
class ReferenceRow:
    """One data row from references.md."""

    timestamp: str
    url: str
    title: str
    uploader: str
    source: str
    extra: str = ''
    category: str = ''
    role: str = ''
    channel_id: str = ''
    line_number: int = 0
    raw: str = ''

    @property
    def has_meta(self) -> bool:
        return bool(self.category or self.role or self.channel_id)


@dataclass
class MigrationState:
    """In-memory file during a multi-step upgrade.

    ``lines`` are full file lines (including newlines). ``version`` is the
    logical format version *after* steps applied so far (before final header
    rewrite, body-only lines may still lack a header).
    """

    lines: List[str]
    version: int
    notes: List[str]


# Type of one N → N+1 upgrade function.
MigrationFn = Callable[[MigrationState], MigrationState]


# ---------------------------------------------------------------------------
# Layered upgrade steps (append only — never reorder or edit old steps lightly)
# ---------------------------------------------------------------------------
#
# HOW TO ADD VERSION 3 (example for future you / other maintainers):
#
#   1. Bump REFERENCES_FORMAT_VERSION to 3.
#   2. Define:
#
#         def _migrate_2_to_3(state: MigrationState) -> MigrationState:
#             """v2 → v3: <one-line summary of the contract change>.
#
#             Detailed notes:
#               - What old rows looked like
#               - What new rows look like
#               - What is left lazy (e.g. backfill on ref-enrich) vs rewritten now
#             """
#             # mutate state.lines as needed
#             state.version = 3
#             state.notes.append('2→3: …')
#             return state
#
#   3. Append to MIGRATION_STEPS:
#         (2, 3, _migrate_2_to_3),
#
#   4. Update build_header() format comment to describe v3.
#   5. Add a unit test that starts at v1 (or v2) and lands on v3 with
#      migration-path listing every hop.
#
# Unversioned/legacy files enter the chain at version 1 (see read_format_version
# + effective_version). So a file from 2023 runs: 1→2, then 2→3, …
# ---------------------------------------------------------------------------


def _migrate_1_to_2(state: MigrationState) -> MigrationState:
    """v1 → v2: introduce version header; drop obsolete ``Date|URL|…`` banner.

    v1 (implicit):
      - No ``# ref-references version=`` line.
      - Optional first line ``Date|URL|Title|Source|…`` (typo variants included).
      - Data: ``timestamp|[url]|(title)|uploader|source[|extra…]``

    v2:
      - Header block with version=2 and format notes.
      - Same data rows (unchanged).
      - Optional trailing ``|@meta|category|role|channel_id`` added later by
        ``ref-enrich`` (not bulk-rewritten here — keeps migrate O(header) fast
        on 20k+ line files).

    Side store (not in this file): ``enrichment/<platform>/…`` meta cards.
    """
    new_lines: List[str] = []
    for line in state.lines:
        stripped = line.strip()
        # Drop any previous managed header lines (re-applied at end of chain).
        if any(stripped.startswith(p) for p in _MANAGED_HEADER_PREFIXES):
            continue
        if is_legacy_header(stripped):
            continue
        new_lines.append(line if line.endswith('\n') else line + '\n')

    state.lines = new_lines
    state.version = 2
    state.notes.append(
        '1→2: add version header; drop legacy Date|URL banner; '
        '@meta fields optional (filled by ref-enrich)'
    )
    return state


# Ordered chain: (from_version, to_version, function).
# Only consecutive hops; migrate_references_file walks current → target.
MIGRATION_STEPS: Sequence[Tuple[int, int, MigrationFn]] = (
    (1, 2, _migrate_1_to_2),
    # (2, 3, _migrate_2_to_3),  # ← future: uncomment/add when REFERENCES_FORMAT_VERSION is 3
)


def is_comment_or_blank(line: str) -> bool:
    """Return True for blank lines and ``#`` comments/headers."""
    stripped = line.strip()
    return (not stripped) or stripped.startswith('#')


def is_legacy_header(line: str) -> bool:
    """Return True for the old ``Date|URL|Title|…`` header row."""
    return bool(_LEGACY_HEADER_RE.match(line.strip()))


def read_format_version(path: str) -> Optional[int]:
    """Return the version from a header, or None if the file has no version.

    ``None`` means unversioned legacy content (treated as version 1 for upgrades).
    """
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(HEADER_PREFIX):
                raw = stripped[len(HEADER_PREFIX):].strip().split()[0]
                try:
                    return int(raw)
                except ValueError:
                    return None
            # First real content without version header → unversioned (v1).
            if is_legacy_header(stripped) or _LINE_RE.match(stripped):
                return None
            if stripped.startswith('#'):
                continue
            return None
    return None


def effective_version(path: str) -> int:
    """Logical version for migration: unversioned files are :data:`LEGACY_UNVERSIONED`."""
    version = read_format_version(path)
    if version is None:
        return LEGACY_UNVERSIONED
    return version


def build_header(
    version: int = REFERENCES_FORMAT_VERSION,
    *,
    migration_path: Optional[Sequence[str]] = None,
) -> str:
    """Return the standard file header block (including trailing newline)."""
    lines = [
        f'{HEADER_PREFIX}{version}',
        (
            f'# format: timestamp|[url]|(title)|uploader|source[|extra…]'
            f'[|{META_SENTINEL}|category|role|channel_id]'
        ),
        '# enrichment: enrichment/<platform>/videos|channels (meta cards)',
        f'# migrated: {datetime.now().strftime("%Y-%m-%dT%H:%M:%S")}',
    ]
    if migration_path:
        # Records which hops ran, e.g. "1→2; 2→3" — useful when upgrading
        # a multi-year-old file through several steps in one go.
        lines.append('# migration-path: ' + '; '.join(migration_path))
    return '\n'.join(lines) + '\n'


def parse_data_line(line: str, line_number: int = 0) -> Optional[ReferenceRow]:
    """Parse a single data line into :class:`ReferenceRow`."""
    stripped = line.rstrip('\n')
    if not stripped or is_comment_or_blank(stripped) or is_legacy_header(stripped):
        return None
    match = _LINE_RE.match(stripped)
    if not match:
        return None

    rest = match.group('rest')
    category = ''
    role = ''
    channel_id = ''

    # Split off trailing @meta|category|role|channel_id if present.
    meta_idx = rest.rfind(f'|{META_SENTINEL}|')
    if meta_idx == -1 and rest.startswith(f'{META_SENTINEL}|'):
        meta_blob = rest
        core_rest = ''
    elif meta_idx != -1:
        meta_blob = rest[meta_idx + 1:]  # starts with @meta|...
        core_rest = rest[:meta_idx]
    else:
        meta_blob = ''
        core_rest = rest

    if meta_blob:
        # @meta|category|role|channel_id
        meta_parts = meta_blob.split('|')
        if len(meta_parts) >= 2:
            category = meta_parts[1]
        if len(meta_parts) >= 3:
            role = meta_parts[2]
        if len(meta_parts) >= 4:
            channel_id = meta_parts[3]

    parts = core_rest.split('|') if core_rest else []
    uploader = ''
    source = ''
    extra = ''

    source_idx = next(
        (i for i, part in enumerate(parts) if part in _SOURCE_MARKERS),
        None,
    )
    if source_idx is not None:
        uploader = '|'.join(parts[:source_idx]).strip()
        source = parts[source_idx]
        extra = '|'.join(parts[source_idx + 1:]).strip()
    elif len(parts) >= 2:
        uploader = parts[0].strip()
        source = parts[1].strip()
        extra = '|'.join(parts[2:]).strip()
    elif parts:
        uploader = parts[0].strip()

    return ReferenceRow(
        timestamp=match.group('ts'),
        url=match.group('url').lstrip('_'),
        title=match.group('title'),
        uploader=uploader,
        source=source,
        extra=extra,
        category=category,
        role=role,
        channel_id=channel_id,
        line_number=line_number,
        raw=stripped,
    )


def format_data_line(row: ReferenceRow) -> str:
    """Serialize a row (no trailing newline)."""
    pieces = [
        row.timestamp,
        f'[{row.url}]',
        f'({row.title})',
        row.uploader,
        row.source or 'General',
    ]
    if row.extra:
        pieces.append(row.extra)
    if row.category or row.role or row.channel_id:
        pieces.extend([
            META_SENTINEL,
            row.category or '',
            row.role or '',
            row.channel_id or '',
        ])
    return '|'.join(pieces)


def iter_data_rows(path: str) -> Iterator[ReferenceRow]:
    """Yield parsed data rows from ``path`` (skips comments/legacy header)."""
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        for line_number, line in enumerate(handle, start=1):
            row = parse_data_line(line, line_number=line_number)
            if row is not None:
                yield row


def needs_migration(path: str) -> bool:
    """True when the file is behind REFERENCES_FORMAT_VERSION."""
    if not os.path.isfile(path):
        return False
    return effective_version(path) < REFERENCES_FORMAT_VERSION


def _steps_from_to(from_version: int, to_version: int) -> List[Tuple[int, int, MigrationFn]]:
    """Select ordered migration hops covering ``from_version`` → ``to_version``."""
    if from_version >= to_version:
        return []
    steps: List[Tuple[int, int, MigrationFn]] = []
    current = from_version
    by_from = {frm: (frm, to, fn) for frm, to, fn in MIGRATION_STEPS}
    while current < to_version:
        if current not in by_from:
            raise ValueError(
                f'No migration step registered from version {current} toward '
                f'{to_version}. Available steps: '
                + ', '.join(f'{a}→{b}' for a, b, _ in MIGRATION_STEPS)
            )
        frm, to, fn = by_from[current]
        if to <= frm:
            raise ValueError(f'Invalid migration step {frm}→{to}')
        steps.append((frm, to, fn))
        current = to
    if current != to_version:
        raise ValueError(
            f'Migration chain from {from_version} ended at {current}, '
            f'not target {to_version}'
        )
    return steps


def migrate_references_file(
    path: str,
    *,
    backup: bool = True,
    compress: bool = True,
    target_version: int = REFERENCES_FORMAT_VERSION,
) -> Tuple[bool, str]:
    """Upgrade ``path`` from its current version to ``target_version``.

    Runs every registered step in order (e.g. 1→2, then 2→3) so a much older
    ``references.md`` layers upgrades correctly. One backup is taken before
    any step mutates the file (gzip by default).

    Returns:
        ``(changed, message)``
    """
    if not os.path.isfile(path):
        return False, f'File not found: {path}'

    start_version = effective_version(path)
    if start_version > target_version:
        raise ValueError(
            f'references.md is version {start_version}, but this ref-cli only '
            f'understands up to {target_version}. Upgrade ref-cli.'
        )
    if start_version == target_version:
        # Still rewrite header if file was unversioned-as-v1? No — v1 with no
        # header is start_version 1; only equal when already at target.
        # If header says target already, done.
        if read_format_version(path) == target_version:
            return False, f'Already at version {target_version}'
        # Edge: effective v1 unversioned equals target only if target is 1.
        if target_version == LEGACY_UNVERSIONED and read_format_version(path) is None:
            return False, f'Already at legacy version {target_version}'

    steps = _steps_from_to(start_version, target_version)
    if not steps:
        return False, f'Already at version {start_version}'

    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        original_lines = handle.readlines()

    state = MigrationState(
        lines=list(original_lines),
        version=start_version,
        notes=[],
    )

    # Apply each hop. Steps are responsible for body transforms; header is
    # normalized once at the end so intermediate versions don't thrash disk.
    path_labels: List[str] = []
    for frm, to, fn in steps:
        if state.version != frm:
            raise ValueError(
                f'Migration invariant broken: about to run {frm}→{to} but '
                f'state.version is {state.version}'
            )
        state = fn(state)
        if state.version != to:
            raise ValueError(
                f'Migration step {frm}→{to} left state.version={state.version}'
            )
        path_labels.append(f'{frm}→{to}')

    # Strip managed header lines from body, then write fresh header + body.
    body: List[str] = []
    for line in state.lines:
        stripped = line.strip()
        if any(stripped.startswith(p) for p in _MANAGED_HEADER_PREFIXES):
            continue
        body.append(line if line.endswith('\n') else line + '\n')

    backup_path = ''
    if backup:
        from ref_cli.backup_util import backup_file
        backup_path = backup_file(path, compress=compress, style='suffix')

    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(build_header(target_version, migration_path=path_labels or None))
        handle.writelines(body)

    hops = '; '.join(path_labels) if path_labels else f'{start_version}→{target_version}'
    msg = (
        f'Migrated references.md {start_version}→{target_version} '
        f'via [{hops}]'
    )
    if state.notes:
        msg += ' | ' + ' | '.join(state.notes)
    if backup_path:
        msg += f' (backup: {backup_path})'
    return True, msg


def ensure_references_migrated(
    path: str,
    *,
    backup: bool = True,
    compress: bool = True,
) -> Optional[str]:
    """Migrate if needed. Returns a human message when a change was made."""
    if not needs_migration(path):
        return None
    changed, message = migrate_references_file(
        path, backup=backup, compress=compress,
    )
    return message if changed else None


def apply_row_updates(
    path: str,
    updates: Sequence[Tuple[int, ReferenceRow]],
    *,
    backup: bool = False,
    compress: bool = True,
) -> int:
    """Rewrite ``path`` applying ``(line_number, new_row)`` updates.

    Line numbers are 1-based as from :func:`iter_data_rows`. Returns count updated.
    """
    if not updates:
        return 0
    by_line = {ln: row for ln, row in updates}
    if backup:
        from ref_cli.backup_util import backup_file
        backup_file(path, compress=compress, style='suffix')

    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        lines = handle.readlines()

    changed = 0
    for idx, line in enumerate(lines):
        line_no = idx + 1
        if line_no not in by_line:
            continue
        new_line = format_data_line(by_line[line_no]) + '\n'
        if lines[idx] != new_line:
            lines[idx] = new_line
            changed += 1

    with open(path, 'w', encoding='utf-8') as handle:
        handle.writelines(lines)
    return changed


def with_meta(
    row: ReferenceRow,
    *,
    category: str = '',
    role: str = '',
    channel_id: str = '',
) -> ReferenceRow:
    """Return a copy of ``row`` with meta fields set."""
    return replace(
        row,
        category=category or row.category,
        role=role or row.role,
        channel_id=channel_id or row.channel_id,
    )
