"""Scan references.md and rank trusted advisors.

Covers YouTube channels, X handles, and web/blog authors you return to
often. Streaming scan so multi-million-token reference files stay
memory-friendly.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.utils.colors import dim, error, info, success, warning

# ---------------------------------------------------------------------------
# Line parsing
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})'
    r'\|\[(?P<url>[^\]]+)\]'
    r'\|\((?P<title>.*)\)\|'
    r'(?P<rest>.*)$'
)

# Known source markers written by ref-cli (field after uploader).
_SOURCE_MARKERS = frozenset({'YouTube', 'General', 'Rumble'})

_X_HOSTS = frozenset({'x.com', 'twitter.com', 'www.x.com', 'www.twitter.com'})
_YT_HOSTS = frozenset({
    'youtube.com',
    'www.youtube.com',
    'm.youtube.com',
    'youtu.be',
    'www.youtu.be',
})

# Non-user path segments on X/Twitter (skip when extracting handles).
_X_RESERVED = frozenset({
    'i', 'intent', 'search', 'hashtag', 'share', 'home', 'explore',
    'settings', 'messages', 'notifications', 'compose', 'login',
    'signup', 'tos', 'privacy', 'about', 'help', 'download',
})

# "Display Name on X: \"tweet text...\""
_X_TITLE_NAME_RE = re.compile(r'^(?P<name>.+?) on X:\s*', re.DOTALL)

_HANDLE_RE = re.compile(
    r'(?:x\.com|twitter\.com)/@?(?P<handle>[A-Za-z0-9_]{1,15})(?:/|$)',
    re.IGNORECASE,
)

# Medium-style "Title | by Author Name | Publication"
_BY_AUTHOR_RE = re.compile(
    r'\|\s*by\s+([^|]+?)(?:\s*\||\s*$)',
    re.IGNORECASE,
)

_MEDIUM_AT_RE = re.compile(r'/@(?P<user>[^/?#]+)', re.IGNORECASE)

# Path segments that are not Medium publications/authors.
_MEDIUM_PATH_RESERVED = frozenset({
    'm', 'me', 'tag', 'tags', 'search', 'topic', 'topics', 'plans',
    'about', 'jobs', 'creators', 'new-story', 'partner-program',
    'membership', 'list', 'lists', 'following', 'followers',
})

# Hosts that are feeds/apps/marketplaces — not "blog authors".
_WEB_SKIP_HOSTS = frozenset({
    'reddit.com',
    'old.reddit.com',
    'np.reddit.com',
    'github.com',
    'gist.github.com',
    'gitlab.com',
    'bitbucket.org',
    'discord.com',
    'cdn.discordapp.com',
    'amazon.com',
    'amazon.ca',
    'amazon.co.uk',
    'tiktok.com',
    'facebook.com',
    'fb.com',
    'instagram.com',
    'linkedin.com',
    'wikipedia.org',
    'en.wikipedia.org',
    'stackoverflow.com',
    'stackexchange.com',
    'google.com',
    'docs.google.com',
    'drive.google.com',
    'maps.google.com',
    'news.google.com',
    'play.google.com',
    'apple.com',
    'microsoft.com',
    'bing.com',
    'duckduckgo.com',
    'perplexity.ai',
    'chatgpt.com',
    'chat.openai.com',
    'claude.ai',
    'search.app',
    'nyaa.si',
    'arxiv.org',  # paper repo, not a blog voice
    'rumble.com',  # video host; no reliable channel field in General rows
    'doi.org',
    'npmjs.com',
    'pypi.org',
    'crates.io',
    'huggingface.co',  # model hub; path authors could be added later
})

_WEB_SKIP_SUFFIXES = (
    '.reddit.com',
    '.amazon.com',
    '.amazon.ca',
    '.wikipedia.org',
    '.stackexchange.com',
    '.google.com',
)

# Medium network / common blogging hosts where author-level identity is preferred.
_MEDIUM_NETWORK_HOSTS = frozenset({
    'medium.com',
    'levelup.gitconnected.com',
    'gitconnected.com',
    'towardsdatascience.com',
    'pub.towardsai.net',
    'towardsai.net',
    'generativeai.pub',
    'pub.neuralnotions.ai',
    'towardsdeeplearning.com',
    'betterprogramming.pub',
    'javascript.plainenglish.io',
    'python.plainenglish.io',
    'blog.devgenius.io',
    'writingcooperative.com',
})

_ALL_PLATFORMS = ('youtube', 'x', 'web')


@dataclass
class ReferenceEntry:
    """One parsed row from references.md."""

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


@dataclass
class AdvisorIdentity:
    """Resolved advisor key for one reference entry."""

    platform: str  # youtube | x | web
    key: str
    display_name: str
    handle: str = ''
    profile_url: str = ''


@dataclass
class AdvisorStats:
    """Aggregated stats for one advisor identity."""

    platform: str
    key: str
    display_name: str
    count: int = 0
    first_seen: str = ''
    last_seen: str = ''
    sample_urls: List[str] = field(default_factory=list)
    sample_titles: List[str] = field(default_factory=list)
    handle: str = ''
    profile_url: str = ''
    categories: Dict[str, int] = field(default_factory=dict)
    roles: Dict[str, int] = field(default_factory=dict)

    def add(
        self,
        timestamp: str,
        url: str,
        title: str,
        *,
        display_name: Optional[str] = None,
        category: str = '',
        role: str = '',
        max_samples: int = 3,
    ) -> None:
        self.count += 1
        if not self.first_seen or timestamp < self.first_seen:
            self.first_seen = timestamp
        if not self.last_seen or timestamp > self.last_seen:
            self.last_seen = timestamp
        if display_name and display_name.strip():
            cleaned = display_name.strip()
            # Prefer a human name over a bare key/handle/domain.
            if (
                not self.display_name
                or self.display_name == self.key
                or self.display_name.casefold() == self.key
                or (
                    self.handle
                    and self.display_name.casefold() == self.handle.lstrip('@').casefold()
                )
            ):
                self.display_name = cleaned
        if category:
            self.categories[category] = self.categories.get(category, 0) + 1
        if role:
            self.roles[role] = self.roles.get(role, 0) + 1
        if len(self.sample_urls) < max_samples and url not in self.sample_urls:
            self.sample_urls.append(url)
        if (
            len(self.sample_titles) < max_samples
            and title
            and title not in self.sample_titles
        ):
            self.sample_titles.append(title)

    @property
    def dominant_role(self) -> str:
        if not self.roles:
            return ''
        return max(self.roles.items(), key=lambda kv: kv[1])[0]

    @property
    def dominant_category(self) -> str:
        if not self.categories:
            return ''
        return max(self.categories.items(), key=lambda kv: kv[1])[0]


def parse_line(line: str, line_number: int = 0) -> Optional[ReferenceEntry]:
    """Parse a references.md data line (including optional ``@meta`` fields)."""
    # Prefer shared format parser (handles @meta + pipe uploaders).
    from ref_cli.references_format import parse_data_line

    row = parse_data_line(line, line_number=line_number)
    if row is None:
        return None
    return ReferenceEntry(
        timestamp=row.timestamp,
        url=row.url,
        title=row.title,
        uploader=row.uploader,
        source=row.source,
        extra=row.extra,
        category=row.category,
        role=row.role,
        channel_id=row.channel_id,
        line_number=row.line_number,
    )


def host_of(url: str) -> str:
    """Return lowercase hostname without a leading www."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001 - bad URL, treat as empty
        return ''
    if host.startswith('www.'):
        host = host[4:]
    return host


def platform_of(url: str) -> Optional[str]:
    """Return ``youtube``, ``x``, ``web``, or None when unusable."""
    host = host_of(url)
    if not host:
        return None
    if host in _YT_HOSTS or host.endswith('.youtube.com'):
        return 'youtube'
    if host in _X_HOSTS or host in {'mobile.twitter.com', 'mobile.x.com'}:
        return 'x'
    if _is_skipped_web_host(host):
        return None
    return 'web'


def _is_skipped_web_host(host: str) -> bool:
    if host in _WEB_SKIP_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in _WEB_SKIP_SUFFIXES)


def extract_x_handle(url: str) -> Optional[str]:
    """Extract a lowercase X/Twitter handle from a status or profile URL."""
    match = _HANDLE_RE.search(url)
    if not match:
        return None
    handle = match.group('handle').lower()
    if handle in _X_RESERVED:
        return None
    return handle


def extract_x_display_name(title: str) -> Optional[str]:
    """Pull display name from titles like ``Name on X: "tweet..."``."""
    match = _X_TITLE_NAME_RE.match(title or '')
    if not match:
        return None
    name = match.group('name').strip()
    return name or None


def extract_by_author(title: str) -> Optional[str]:
    """Pull author from Medium-style titles: ``Title | by Name | Pub``."""
    if not title:
        return None
    # Skip bot-challenge / empty Medium titles.
    stripped = title.strip()
    if stripped in {'Just a moment...', 'Medium', 'Attention Required! | Cloudflare'}:
        return None
    match = _BY_AUTHOR_RE.search(stripped)
    if not match:
        return None
    name = match.group(1).strip().lstrip('@').strip()
    if not name or name.casefold() in {'medium', 'unknown', 'author'}:
        return None
    return name


def _is_medium_network(host: str) -> bool:
    if host in _MEDIUM_NETWORK_HOSTS:
        return True
    if host.endswith('.medium.com'):
        return True
    return False


def resolve_web_advisor(entry: ReferenceEntry) -> Optional[AdvisorIdentity]:
    """Resolve a blog/web author or recurring site from a general URL.

    Preference order:
    1. Medium subdomain authors (``xhinker.medium.com``)
    2. Medium ``/@handle`` path
    3. ``| by Author |`` in the page title (Medium network + any blog)
    4. Medium publication slug (weaker, still a recurring voice)
    5. Site domain for personal/company blogs you return to
    """
    host = host_of(entry.url)
    if not host or _is_skipped_web_host(host):
        return None

    parsed = urlparse(entry.url)
    path = parsed.path or '/'

    # 1) author.medium.com
    if host.endswith('.medium.com') and host != 'medium.com':
        slug = host[: -len('.medium.com')]
        if slug and slug not in {'www', 'policy', 'help', 'status'}:
            return AdvisorIdentity(
                platform='web',
                key=f'medium:{slug.casefold()}',
                display_name=slug,
                handle=f'@{slug}' if re.fullmatch(r'[A-Za-z0-9_]+', slug) else '',
                profile_url=f'https://{slug}.medium.com',
            )

    # 2) medium.com/@user
    if host == 'medium.com':
        at_match = _MEDIUM_AT_RE.search(path)
        if at_match:
            user = at_match.group('user')
            return AdvisorIdentity(
                platform='web',
                key=f'medium:{user.casefold()}',
                display_name=user,
                handle=f'@{user}',
                profile_url=f'https://medium.com/@{user}',
            )

    # 3) title "by Author" — strong signal on Medium network and blogs
    by_author = extract_by_author(entry.title)
    if by_author:
        profile = f'https://{host}'
        handle = ''
        key_prefix = 'author'
        if _is_medium_network(host) or host == 'medium.com':
            key_prefix = 'medium'
            # Keep Medium authors mergeable across publications.
            if by_author.startswith('@'):
                slug = by_author.lstrip('@')
                return AdvisorIdentity(
                    platform='web',
                    key=f'medium:{slug.casefold()}',
                    display_name=slug,
                    handle=f'@{slug}',
                    profile_url=f'https://medium.com/@{slug}',
                )
        return AdvisorIdentity(
            platform='web',
            key=f'{key_prefix}:{by_author.casefold()}',
            display_name=by_author,
            handle=handle,
            profile_url=profile,
        )

    # 4) medium.com/<publication>/...
    if host == 'medium.com':
        parts = [p for p in path.split('/') if p]
        if parts and parts[0] not in _MEDIUM_PATH_RESERVED and not parts[0].startswith('@'):
            pub = parts[0]
            return AdvisorIdentity(
                platform='web',
                key=f'medium-pub:{pub.casefold()}',
                display_name=pub.replace('-', ' '),
                profile_url=f'https://medium.com/{pub}',
            )

    # Substack-style author.substack.com
    if host.endswith('.substack.com') and host != 'substack.com':
        slug = host[: -len('.substack.com')]
        if slug:
            return AdvisorIdentity(
                platform='web',
                key=f'substack:{slug.casefold()}',
                display_name=slug,
                profile_url=f'https://{slug}.substack.com',
            )

    # 5) Recurring site / personal blog by domain
    return AdvisorIdentity(
        platform='web',
        key=f'site:{host}',
        display_name=host,
        profile_url=f'https://{host}',
    )


def resolve_advisor(entry: ReferenceEntry) -> Optional[AdvisorIdentity]:
    """Map one reference entry to an advisor identity, if any."""
    host_platform = platform_of(entry.url)

    if host_platform == 'youtube':
        channel = (entry.uploader or '').strip()
        if not channel or channel in {'YouTube', 'General', 'Rumble'}:
            return None
        return AdvisorIdentity(
            platform='youtube',
            key=channel.casefold(),
            display_name=channel,
        )

    if host_platform == 'x':
        handle = extract_x_handle(entry.url)
        if not handle:
            return None
        display = extract_x_display_name(entry.title) or handle
        return AdvisorIdentity(
            platform='x',
            key=handle,
            display_name=display,
            handle=f'@{handle}',
            profile_url=f'https://x.com/{handle}',
        )

    if host_platform == 'web':
        return resolve_web_advisor(entry)

    return None


def iter_entries(path: str):
    """Stream-parse reference entries from ``path``."""
    with open(path, 'r', encoding='utf-8', errors='replace') as handle:
        for line_number, line in enumerate(handle, start=1):
            entry = parse_line(line, line_number=line_number)
            if entry is not None:
                yield entry


def scan_advisors(
    path: str,
    *,
    platforms: Optional[Sequence[str]] = None,
    min_count: int = 1,
    max_samples: int = 3,
    roles: Optional[Sequence[str]] = None,
    exclude_roles: Optional[Sequence[str]] = None,
) -> List[AdvisorStats]:
    """Scan ``path`` and return advisors ranked by save count (desc).

    Args:
        path: Path to references.md.
        platforms: Subset of ``youtube`` / ``x`` / ``web``. Default all three.
        min_count: Drop advisors with fewer saves than this.
        max_samples: Cap sample URLs/titles kept per advisor.
        roles: If set, keep only advisors whose dominant enriched role is in this set.
        exclude_roles: Drop advisors whose dominant role is in this set (e.g. music).
    """
    wanted = set(platforms or _ALL_PLATFORMS)
    # Accept blog as alias for web.
    if 'blog' in wanted:
        wanted.discard('blog')
        wanted.add('web')
    role_allow = {r.casefold() for r in roles} if roles else None
    role_deny = {r.casefold() for r in (exclude_roles or ())}

    bucket: Dict[Tuple[str, str], AdvisorStats] = {}

    for entry in iter_entries(path):
        identity = resolve_advisor(entry)
        if identity is None or identity.platform not in wanted:
            continue

        bucket_key = (identity.platform, identity.key)
        stats = bucket.get(bucket_key)
        if stats is None:
            stats = AdvisorStats(
                platform=identity.platform,
                key=identity.key,
                display_name=identity.display_name,
                handle=identity.handle,
                profile_url=identity.profile_url,
            )
            bucket[bucket_key] = stats
        elif identity.profile_url and not stats.profile_url:
            stats.profile_url = identity.profile_url
        if identity.handle and not stats.handle:
            stats.handle = identity.handle

        stats.add(
            entry.timestamp,
            entry.url,
            entry.title,
            display_name=identity.display_name,
            category=entry.category,
            role=entry.role,
            max_samples=max_samples,
        )

    advisors = [s for s in bucket.values() if s.count >= min_count]
    if role_allow is not None:
        advisors = [
            s for s in advisors
            if s.dominant_role.casefold() in role_allow
        ]
    if role_deny:
        advisors = [
            s for s in advisors
            if s.dominant_role.casefold() not in role_deny
        ]
    advisors.sort(key=lambda s: (-s.count, s.platform, s.display_name.casefold()))
    return advisors


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _target_for(adv: AdvisorStats) -> str:
    if adv.profile_url:
        return adv.profile_url
    if adv.platform == 'youtube':
        return f'youtube channel: {adv.display_name}'
    if adv.platform == 'x' and adv.handle:
        return f'https://x.com/{adv.handle.lstrip("@")}'
    return adv.display_name


def advisors_to_dicts(advisors: Sequence[AdvisorStats]) -> List[dict]:
    """Serialize advisor stats to plain dicts (JSON/CSV friendly)."""
    rows = []
    for rank, adv in enumerate(advisors, start=1):
        rows.append({
            'rank': rank,
            'platform': adv.platform,
            'key': adv.key,
            'display_name': adv.display_name,
            'handle': adv.handle,
            'profile_url': adv.profile_url,
            'count': adv.count,
            'first_seen': adv.first_seen,
            'last_seen': adv.last_seen,
            'category': adv.dominant_category,
            'role': adv.dominant_role,
            'sample_urls': list(adv.sample_urls),
            'sample_titles': list(adv.sample_titles),
            'target': _target_for(adv),
        })
    return rows


def _display_width(text: str) -> int:
    """Approximate terminal column width (handles wide East-Asian glyphs)."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        # Treat fullwidth / wide as 2 columns; emoji often report as neutral (1).
        if unicodedata.east_asian_width(char) in ('F', 'W'):
            width += 2
        else:
            width += 1
    return width


def _clip(text: str, max_width: int) -> str:
    """Truncate ``text`` to ``max_width`` display columns, with ellipsis."""
    cleaned = (text or '').replace('\n', ' ').replace('\r', ' ').strip()
    if max_width <= 0:
        return ''
    if _display_width(cleaned) <= max_width:
        return cleaned
    if max_width <= 3:
        # Extremely tight column — just slice codepoints.
        return cleaned[:max_width]
    out: List[str] = []
    width = 0
    limit = max_width - 3
    for char in cleaned:
        char_w = 2 if unicodedata.east_asian_width(char) in ('F', 'W') else 1
        if unicodedata.combining(char):
            char_w = 0
        if width + char_w > limit:
            break
        out.append(char)
        width += char_w
    return ''.join(out) + '...'


def _pad(text: str, width: int, *, align: str = 'left') -> str:
    """Pad ``text`` to ``width`` display columns."""
    text = text or ''
    pad = max(0, width - _display_width(text))
    if align == 'right':
        return (' ' * pad) + text
    return text + (' ' * pad)


def format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    aligns: Optional[Sequence[str]] = None,
    max_widths: Optional[Sequence[Optional[int]]] = None,
) -> List[str]:
    """Build a fixed-width plain-text table that lines up in a terminal.

    Args:
        headers: Column headers.
        rows: Data rows (same length as headers).
        aligns: Per-column ``left`` or ``right`` (default left).
        max_widths: Optional per-column display-width caps (None = no cap
            beyond content). Useful to keep sample titles from blowing out
            the terminal.
    """
    if not headers:
        return []
    n = len(headers)
    aligns = list(aligns or ['left'] * n)
    max_widths = list(max_widths or [None] * n)
    if len(aligns) != n or len(max_widths) != n:
        raise ValueError('aligns/max_widths must match header count')

    # Normalize / clip cells first so widths are stable.
    norm_headers = [
        _clip(h, mw) if mw is not None else (h or '')
        for h, mw in zip(headers, max_widths)
    ]
    norm_rows: List[List[str]] = []
    for row in rows:
        cells: List[str] = []
        for idx in range(n):
            raw = row[idx] if idx < len(row) else ''
            mw = max_widths[idx]
            cells.append(_clip(str(raw), mw) if mw is not None else str(raw))
        norm_rows.append(cells)

    col_widths = [_display_width(h) for h in norm_headers]
    for row in norm_rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], _display_width(cell))

    def fmt_row(cells: Sequence[str]) -> str:
        parts = [
            _pad(cells[i], col_widths[i], align=aligns[i])
            for i in range(n)
        ]
        return '  '.join(parts)

    sep = '  '.join('-' * w for w in col_widths)
    lines = [fmt_row(norm_headers), sep]
    lines.extend(fmt_row(row) for row in norm_rows)
    return lines


def render_markdown(advisors: Sequence[AdvisorStats], *, path: str) -> str:
    """Human-readable ranked list with terminal-aligned columns."""
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines: List[str] = [
        'Trusted Advisors',
        '================',
        '',
        f'Source:    {path}',
        f'Generated: {generated}',
        f'Total:     {len(advisors)}',
        '',
        'Ranked by how often you saved their content. Use these identities to',
        'target YouTube/X transcripts and blog archives for voice modeling.',
        '',
    ]

    by_platform: Dict[str, List[AdvisorStats]] = defaultdict(list)
    for adv in advisors:
        by_platform[adv.platform].append(adv)

    if by_platform.get('youtube'):
        lines.append('YouTube channels')
        lines.append('----------------')
        rows = [
            [
                str(i),
                adv.display_name,
                str(adv.count),
                adv.dominant_role or '-',
                adv.dominant_category or '-',
                adv.first_seen[:10],
                adv.last_seen[:10],
                adv.sample_titles[0] if adv.sample_titles else '',
            ]
            for i, adv in enumerate(by_platform['youtube'], start=1)
        ]
        lines.extend(format_table(
            ['Rank', 'Channel', 'Saves', 'Role', 'Category', 'First', 'Last', 'Sample title'],
            rows,
            aligns=['right', 'left', 'right', 'left', 'left', 'left', 'left', 'left'],
            max_widths=[4, 32, 6, 10, 18, 10, 10, 40],
        ))
        lines.append('')

    if by_platform.get('x'):
        lines.append('X handles')
        lines.append('---------')
        rows = [
            [
                str(i),
                adv.handle,
                adv.display_name,
                str(adv.count),
                adv.first_seen[:10],
                adv.last_seen[:10],
                adv.profile_url,
            ]
            for i, adv in enumerate(by_platform['x'], start=1)
        ]
        lines.extend(format_table(
            ['Rank', 'Handle', 'Display name', 'Saves', 'First', 'Last', 'Profile'],
            rows,
            aligns=['right', 'left', 'left', 'right', 'left', 'left', 'left'],
            max_widths=[4, 18, 28, 6, 10, 10, 36],
        ))
        lines.append('')

    if by_platform.get('web'):
        lines.append('Web / blog authors')
        lines.append('------------------')
        rows = [
            [
                str(i),
                adv.display_name,
                adv.key,
                str(adv.count),
                adv.first_seen[:10],
                adv.last_seen[:10],
                _target_for(adv),
            ]
            for i, adv in enumerate(by_platform['web'], start=1)
        ]
        lines.extend(format_table(
            ['Rank', 'Author / site', 'Key', 'Saves', 'First', 'Last', 'Target'],
            rows,
            aligns=['right', 'left', 'left', 'right', 'left', 'left', 'left'],
            max_widths=[4, 28, 32, 6, 10, 10, 40],
        ))
        lines.append('')

    if not advisors:
        lines.append('(No advisors matched the current filters.)')
        lines.append('')

    lines.extend([
        'Targeting notes',
        '---------------',
        '- YouTube: match on channel/uploader name (no channel ID stored).',
        '- X: use profile URL / @handle; display names from "Name on X: ...".',
        '- Web/blogs: Medium @handle / author.medium.com / "| by Author |",',
        '  else recurring site domain. Aggregators (Reddit, GitHub, arXiv, …) skipped.',
        '- Raise --min-count (e.g. 3 or 5) to keep only frequent voices.',
        '',
    ])
    return '\n'.join(lines)


def render_json(advisors: Sequence[AdvisorStats], *, path: str) -> str:
    """JSON document with advisor list and scan metadata."""
    payload = {
        'source': path,
        'generated': datetime.now().isoformat(timespec='seconds'),
        'total': len(advisors),
        'advisors': advisors_to_dicts(advisors),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + '\n'


def render_csv(advisors: Sequence[AdvisorStats]) -> str:
    """CSV with one row per advisor."""
    buf = io.StringIO()
    fieldnames = [
        'rank', 'platform', 'key', 'display_name', 'handle', 'profile_url',
        'count', 'category', 'role', 'first_seen', 'last_seen', 'target',
        'sample_title', 'sample_url',
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in advisors_to_dicts(advisors):
        writer.writerow({
            'rank': row['rank'],
            'platform': row['platform'],
            'key': row['key'],
            'display_name': row['display_name'],
            'handle': row['handle'],
            'profile_url': row['profile_url'],
            'count': row['count'],
            'category': row.get('category', ''),
            'role': row.get('role', ''),
            'first_seen': row['first_seen'],
            'last_seen': row['last_seen'],
            'target': row['target'],
            'sample_title': (row['sample_titles'] or [''])[0],
            'sample_url': (row['sample_urls'] or [''])[0],
        })
    return buf.getvalue()


def render(
    advisors: Sequence[AdvisorStats],
    *,
    path: str,
    fmt: str,
) -> str:
    """Render advisors in ``markdown``, ``json``, or ``csv``."""
    fmt = fmt.lower()
    if fmt in ('md', 'markdown'):
        return render_markdown(advisors, path=path)
    if fmt == 'json':
        return render_json(advisors, path=path)
    if fmt == 'csv':
        return render_csv(advisors)
    raise ValueError(f'Unsupported format: {fmt}')


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def default_references_path() -> str:
    """Resolve the configured references.md path (same as main CLI)."""
    try:
        from ref_cli.cli import UNIFIED
        return UNIFIED
    except Exception:  # noqa: BLE001 - fall back if config/import fails
        return os.path.expanduser('~/references/references.md')


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the advisors CLI argument parser."""
    from ref_cli import __version__

    parser = argparse.ArgumentParser(
        description=(
            'Scan references.md and list trusted advisors '
            '(YouTube channels, X handles, and web/blog authors ranked by saves).'
        ),
    )
    file_arg = parser.add_argument(
        '--file',
        default=None,
        help='Path to references.md (default: configured references path)',
    )
    file_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        '--platform',
        choices=('all', 'youtube', 'x', 'web', 'blog'),
        default='all',
        help='Limit to one platform (blog is an alias for web; default: all)',
    )
    parser.add_argument(
        '--min-count',
        type=int,
        default=2,
        help='Minimum saves to include an advisor (default: 2)',
    )
    parser.add_argument(
        '--top',
        type=int,
        default=None,
        help='Keep only the top N advisors after filtering',
    )
    parser.add_argument(
        '--format',
        choices=('markdown', 'md', 'json', 'csv'),
        default='markdown',
        help='Output format (default: markdown)',
    )
    output_arg = parser.add_argument(
        '-o', '--output',
        default=None,
        help='Write output to this file instead of stdout',
    )
    output_arg.completer = files_completer()  # type: ignore[attr-defined]
    parser.add_argument(
        '--max-samples',
        type=int,
        default=3,
        help='Sample URLs/titles kept per advisor (default: 3)',
    )
    parser.add_argument(
        '--role',
        action='append',
        default=None,
        metavar='ROLE',
        help=(
            'Only include advisors with this dominant enriched role '
            '(repeatable). Roles come from ref-enrich (@meta), e.g. advisor, music.'
        ),
    )
    parser.add_argument(
        '--exclude-role',
        action='append',
        default=None,
        metavar='ROLE',
        help='Exclude advisors with this dominant role (repeatable), e.g. music',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {__version__}',
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    try:
        return _main(argv)
    except KeyboardInterrupt:
        # Clean Ctrl+C: no traceback (exit 130 is the usual shell convention).
        try:
            print(file=sys.stderr)
            print(warning('Interrupted.'), file=sys.stderr)
        except Exception:  # noqa: BLE001 - stderr may be gone
            pass
        return 130
    except BrokenPipeError:
        # e.g. `ref-advisors | head` — exit quietly.
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        return 0


def _main(argv: Optional[Sequence[str]] = None) -> int:
    """Implementation of :func:`main` (kept separate for interrupt handling)."""
    parser = build_arg_parser()
    # Shell tab completion (no-op unless _ARGCOMPLETE is set by the shell)
    enable_argcomplete(parser)
    args = parser.parse_args(argv)

    path = os.path.expanduser(args.file or default_references_path())
    if not os.path.isfile(path):
        print(error(f'File not found: {path}'), file=sys.stderr)
        return 1
    if args.min_count < 1:
        print(error('--min-count must be a positive integer'), file=sys.stderr)
        return 1
    if args.top is not None and args.top < 1:
        print(error('--top must be a positive integer'), file=sys.stderr)
        return 1
    if args.max_samples < 0:
        print(error('--max-samples must be >= 0'), file=sys.stderr)
        return 1

    platforms: Sequence[str]
    if args.platform == 'all':
        platforms = _ALL_PLATFORMS
    elif args.platform == 'blog':
        platforms = ('web',)
    else:
        platforms = (args.platform,)

    print(info(f'Scanning advisors in {path}'), file=sys.stderr)
    print(
        dim(
            f'platforms={",".join(platforms)} min_count={args.min_count} '
            f'format={args.format}'
        ),
        file=sys.stderr,
    )

    advisors = scan_advisors(
        path,
        platforms=platforms,
        min_count=args.min_count,
        max_samples=args.max_samples,
        roles=args.role,
        exclude_roles=args.exclude_role,
    )
    if args.top is not None:
        advisors = advisors[: args.top]

    text = render(advisors, path=path, fmt=args.format)

    if args.output:
        out_path = os.path.expanduser(args.output)
        parent = os.path.dirname(out_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as handle:
            handle.write(text)
        print(success(f'Wrote {len(advisors)} advisors -> {out_path}'), file=sys.stderr)
    else:
        try:
            sys.stdout.write(text)
            if not text.endswith('\n'):
                sys.stdout.write('\n')
            sys.stdout.flush()
        except BrokenPipeError:
            raise

    yt_n = sum(1 for a in advisors if a.platform == 'youtube')
    x_n = sum(1 for a in advisors if a.platform == 'x')
    web_n = sum(1 for a in advisors if a.platform == 'web')
    print(
        info(
            f'Done: {len(advisors)} advisors '
            f'({yt_n} YouTube, {x_n} X, {web_n} web/blog)'
        ),
        file=sys.stderr,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
