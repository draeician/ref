"""Enrichment store + YouTube meta cards (expandable to other platforms).

Layout under the references base directory (created on demand)::

    enrichment/
      youtube/
        videos/<video_id>.json      # full info card per video
        channels/<channel_id>.json  # rolled-up channel card
      index.jsonl                   # optional append-only fetch log

Thin category/role/channel_id also written onto references.md rows via ``@meta``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def enrichment_root(references_base: str) -> str:
    return os.path.join(os.path.expanduser(references_base), 'enrichment')


def platform_dir(references_base: str, platform: str) -> str:
    return os.path.join(enrichment_root(references_base), platform)


def videos_dir(references_base: str, platform: str = 'youtube') -> str:
    return os.path.join(platform_dir(references_base, platform), 'videos')


def channels_dir(references_base: str, platform: str = 'youtube') -> str:
    return os.path.join(platform_dir(references_base, platform), 'channels')


def index_path(references_base: str) -> str:
    return os.path.join(enrichment_root(references_base), 'index.jsonl')


def ensure_enrichment_dirs(references_base: str, platform: str = 'youtube') -> Dict[str, str]:
    """Create enrichment directory tree if missing. Returns key paths."""
    paths = {
        'root': enrichment_root(references_base),
        'platform': platform_dir(references_base, platform),
        'videos': videos_dir(references_base, platform),
        'channels': channels_dir(references_base, platform),
        'index': index_path(references_base),
    }
    for key in ('root', 'platform', 'videos', 'channels'):
        os.makedirs(paths[key], exist_ok=True)
    return paths


def video_card_path(references_base: str, video_id: str, platform: str = 'youtube') -> str:
    safe = re.sub(r'[^\w.-]', '_', video_id)
    return os.path.join(videos_dir(references_base, platform), f'{safe}.json')


def channel_card_path(references_base: str, channel_id: str, platform: str = 'youtube') -> str:
    safe = re.sub(r'[^\w.-]', '_', channel_id)
    return os.path.join(channels_dir(references_base, platform), f'{safe}.json')


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

# https://developers.google.com/youtube/v3/docs/videoCategories/list
YOUTUBE_CATEGORY_NAMES: Dict[str, str] = {
    '1': 'Film & Animation',
    '2': 'Autos & Vehicles',
    '10': 'Music',
    '15': 'Pets & Animals',
    '17': 'Sports',
    '19': 'Travel & Events',
    '20': 'Gaming',
    '22': 'People & Blogs',
    '23': 'Comedy',
    '24': 'Entertainment',
    '25': 'News & Politics',
    '26': 'Howto & Style',
    '27': 'Education',
    '28': 'Science & Technology',
    '29': 'Nonprofits & Activism',
    '30': 'Movies',
    '31': 'Anime/Animation',
    '32': 'Action/Adventure',
    '33': 'Classics',
    '34': 'Comedy',
    '35': 'Documentary',
    '36': 'Drama',
    '37': 'Family',
    '38': 'Foreign',
    '39': 'Horror',
    '40': 'Sci-Fi/Fantasy',
    '41': 'Thriller',
    '42': 'Shorts',
    '43': 'Shows',
    '44': 'Trailers',
}

_URL_RE = re.compile(r'https?://[^\s<>\"\']+', re.IGNORECASE)

_LINK_BUCKETS = (
    ('github', re.compile(r'(?:https?://)?(?:www\.)?github\.com/[\w.-]+/[\w.-]+', re.I)),
    ('amazon', re.compile(
        r'(?:https?://)?(?:www\.)?(?:amazon\.[a-z.]+|amzn\.to|amzn\.eu)/[^\s]*',
        re.I,
    )),
    ('music', re.compile(
        r'(?:https?://)?(?:open\.spotify\.com|music\.apple\.com|bandcamp\.com|'
        r'soundcloud\.com|music\.youtube\.com)/[^\s]*',
        re.I,
    )),
    ('patreon', re.compile(
        r'(?:https?://)?(?:www\.)?(?:patreon\.com|ko-fi\.com|buymeacoffee\.com)/[^\s]*',
        re.I,
    )),
    ('discord', re.compile(r'(?:https?://)?(?:discord\.gg|discord\.com/invite)/[^\s]*', re.I)),
)


def extract_youtube_video_id(url: str) -> Optional[str]:
    """Return an 11-char video id from common YouTube URL shapes."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return None
    host = (parsed.netloc or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    if host in {'youtu.be'}:
        vid = parsed.path.lstrip('/').split('/')[0]
        return vid if re.fullmatch(r'[\w-]{11}', vid or '') else None
    if 'youtube.com' in host or host == 'youtube.com':
        qs = parse_qs(parsed.query)
        if 'v' in qs and qs['v']:
            vid = qs['v'][0]
            return vid if re.fullmatch(r'[\w-]{11}', vid) else None
        for prefix in ('/shorts/', '/live/', '/embed/', '/v/'):
            if parsed.path.startswith(prefix):
                vid = parsed.path[len(prefix):].split('/')[0]
                return vid if re.fullmatch(r'[\w-]{11}', vid) else None
    return None


def extract_links(text: str) -> Dict[str, List[str]]:
    """Bucket URLs found in description/text into github/amazon/music/…"""
    buckets: Dict[str, List[str]] = {
        'github': [],
        'amazon': [],
        'music': [],
        'patreon': [],
        'discord': [],
        'other': [],
    }
    if not text:
        return buckets
    seen = set()
    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(').,]\'"')
        if url in seen:
            continue
        seen.add(url)
        placed = False
        for name, pattern in _LINK_BUCKETS:
            if pattern.search(url):
                buckets[name].append(url)
                placed = True
                break
        if not placed:
            buckets['other'].append(url)
    return buckets


def infer_role(
    *,
    category_id: str = '',
    category: str = '',
    title: str = '',
    links: Optional[Dict[str, List[str]]] = None,
    duration_sec: Optional[int] = None,
) -> str:
    """Heuristic role for advisor filtering (not ground truth)."""
    links = links or {}
    cat = (category or '').casefold()
    cid = str(category_id or '')
    title_l = (title or '').casefold()

    music_title = any(
        token in title_l
        for token in (
            'copyright free', 'type beat', 'ebm', 'techno mix', 'industrial mix',
            'nightcore', 'lofi mix', 'lo-fi', 'playlist mix',
        )
    )
    if cid == '10' or 'music' in cat or music_title:
        return 'music'
    if links.get('github'):
        return 'advisor'
    if cid in {'27', '28', '26'} or any(
        x in cat for x in ('education', 'science', 'howto', 'technology')
    ):
        # Very long single video can still be a course lecture
        if duration_sec and duration_sec >= 3600 * 2:
            return 'course'
        return 'advisor'
    if cid == '25' or 'news' in cat or 'politics' in cat:
        return 'news'
    if cid in {'20', '1', '23', '24'} or any(
        x in cat for x in ('gaming', 'comedy', 'entertainment', 'film')
    ):
        return 'media'
    if links.get('music') and not links.get('github'):
        return 'music'
    return 'unknown'


def _parse_iso8601_duration(value: str) -> Optional[int]:
    """Parse YouTube API ISO-8601 duration (e.g. PT1H2M10S) to seconds."""
    if not value:
        return None
    match = re.fullmatch(
        r'P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?',
        value,
    )
    if not match:
        return None
    days = int(match.group('days') or 0)
    hours = int(match.group('hours') or 0)
    minutes = int(match.group('minutes') or 0)
    seconds = int(match.group('seconds') or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


@dataclass
class VideoEnrichment:
    """Normalized enrichment result for one YouTube video."""

    video_id: str
    title: str = ''
    channel_id: str = ''
    channel_title: str = ''
    category_id: str = ''
    category: str = ''
    description: str = ''
    tags: List[str] = field(default_factory=list)
    duration_sec: Optional[int] = None
    published_at: str = ''
    links: Dict[str, List[str]] = field(default_factory=dict)
    role: str = 'unknown'
    source: str = ''  # youtube_api | yt_dlp
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_card(self) -> Dict[str, Any]:
        return {
            'schema_version': 1,
            'platform': 'youtube',
            'video_id': self.video_id,
            'fetched_at': datetime.now().isoformat(timespec='seconds'),
            'source': self.source,
            'title': self.title,
            'channel_id': self.channel_id,
            'channel_title': self.channel_title,
            'category_id': self.category_id,
            'category': self.category,
            'description': self.description,
            'tags': list(self.tags),
            'duration_sec': self.duration_sec,
            'published_at': self.published_at,
            'links': self.links,
            'role': self.role,
            'raw': self.raw,
        }


def fetch_youtube_via_api(video_id: str, api_key: str) -> VideoEnrichment:
    """Fetch video metadata with YouTube Data API v3."""
    from googleapiclient.discovery import build

    youtube = build('youtube', 'v3', developerKey=api_key, cache_discovery=False)
    response = youtube.videos().list(
        part='snippet,contentDetails,topicDetails',
        id=video_id,
    ).execute()
    items = response.get('items') or []
    if not items:
        raise ValueError(f'No YouTube API result for video id {video_id}')

    item = items[0]
    snippet = item.get('snippet') or {}
    content = item.get('contentDetails') or {}
    category_id = str(snippet.get('categoryId') or '')
    category = YOUTUBE_CATEGORY_NAMES.get(category_id, category_id)
    description = snippet.get('description') or ''
    links = extract_links(description)
    duration_sec = _parse_iso8601_duration(content.get('duration') or '')
    title = snippet.get('title') or ''
    role = infer_role(
        category_id=category_id,
        category=category,
        title=title,
        links=links,
        duration_sec=duration_sec,
    )
    return VideoEnrichment(
        video_id=video_id,
        title=title,
        channel_id=snippet.get('channelId') or '',
        channel_title=snippet.get('channelTitle') or '',
        category_id=category_id,
        category=category,
        description=description,
        tags=list(snippet.get('tags') or []),
        duration_sec=duration_sec,
        published_at=snippet.get('publishedAt') or '',
        links=links,
        role=role,
        source='youtube_api',
        raw={
            'snippet': snippet,
            'contentDetails': content,
            'topicDetails': item.get('topicDetails') or {},
        },
    )


def fetch_youtube_via_ytdlp(video_id: str) -> VideoEnrichment:
    """Fetch video metadata with yt-dlp JSON (no API key)."""
    url = f'https://www.youtube.com/watch?v={video_id}'
    proc = subprocess.run(
        [
            'yt-dlp',
            '--skip-download',
            '--no-warnings',
            '-J',
            url,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or 'yt-dlp failed').strip()
        raise RuntimeError(err.splitlines()[-1] if err else 'yt-dlp failed')

    data = json.loads(proc.stdout)
    description = data.get('description') or ''
    links = extract_links(description)
    # yt-dlp categories are often a list of strings
    cats = data.get('categories') or []
    category = cats[0] if cats else ''
    category_id = ''
    for cid, name in YOUTUBE_CATEGORY_NAMES.items():
        if name.casefold() == category.casefold():
            category_id = cid
            break
    title = data.get('title') or ''
    duration_sec = data.get('duration')
    if duration_sec is not None:
        try:
            duration_sec = int(duration_sec)
        except (TypeError, ValueError):
            duration_sec = None
    role = infer_role(
        category_id=category_id,
        category=category,
        title=title,
        links=links,
        duration_sec=duration_sec,
    )
    return VideoEnrichment(
        video_id=video_id,
        title=title,
        channel_id=data.get('channel_id') or data.get('uploader_id') or '',
        channel_title=data.get('channel') or data.get('uploader') or '',
        category_id=category_id,
        category=category,
        description=description,
        tags=list(data.get('tags') or []),
        duration_sec=duration_sec,
        published_at=str(data.get('upload_date') or data.get('release_date') or ''),
        links=links,
        role=role,
        source='yt_dlp',
        raw={
            'id': data.get('id'),
            'webpage_url': data.get('webpage_url'),
            'categories': cats,
            'channel_url': data.get('channel_url'),
            'view_count': data.get('view_count'),
        },
    )


def fetch_youtube_video(
    video_id: str,
    *,
    api_key: Optional[str] = None,
    prefer_api: bool = True,
) -> VideoEnrichment:
    """Fetch enrichment; prefer API when key present, else yt-dlp."""
    errors: List[str] = []
    if prefer_api and api_key:
        try:
            return fetch_youtube_via_api(video_id, api_key)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'api: {exc}')
    try:
        return fetch_youtube_via_ytdlp(video_id)
    except Exception as exc:  # noqa: BLE001
        errors.append(f'yt-dlp: {exc}')
    if api_key and not prefer_api:
        try:
            return fetch_youtube_via_api(video_id, api_key)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'api: {exc}')
    raise RuntimeError('; '.join(errors) or 'fetch failed')


def save_video_card(references_base: str, enrichment: VideoEnrichment) -> str:
    """Write video JSON card; return path."""
    ensure_enrichment_dirs(references_base, 'youtube')
    path = video_card_path(references_base, enrichment.video_id)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(enrichment.to_card(), handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    return path


def load_video_card(
    references_base: str,
    video_id: str,
) -> Optional[Dict[str, Any]]:
    path = video_card_path(references_base, video_id)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def update_channel_card(
    references_base: str,
    enrichment: VideoEnrichment,
) -> Optional[str]:
    """Merge this video into a channel rollup card. Return path or None."""
    if not enrichment.channel_id:
        return None
    ensure_enrichment_dirs(references_base, 'youtube')
    path = channel_card_path(references_base, enrichment.channel_id)
    card: Dict[str, Any]
    if os.path.isfile(path):
        with open(path, 'r', encoding='utf-8') as handle:
            card = json.load(handle)
    else:
        card = {
            'schema_version': 1,
            'platform': 'youtube',
            'channel_id': enrichment.channel_id,
            'title': enrichment.channel_title,
            'video_count_enriched': 0,
            'category_counts': {},
            'role_counts': {},
            'link_counts': {
                'github': 0,
                'amazon': 0,
                'music': 0,
                'patreon': 0,
                'discord': 0,
                'other': 0,
            },
            'video_ids': [],
            'dominant_category': '',
            'dominant_role': '',
        }

    card['title'] = enrichment.channel_title or card.get('title') or ''
    card['updated_at'] = datetime.now().isoformat(timespec='seconds')
    card['video_count_enriched'] = int(card.get('video_count_enriched') or 0) + 1

    cat_counts = card.setdefault('category_counts', {})
    if enrichment.category:
        cat_counts[enrichment.category] = int(cat_counts.get(enrichment.category) or 0) + 1

    role_counts = card.setdefault('role_counts', {})
    if enrichment.role:
        role_counts[enrichment.role] = int(role_counts.get(enrichment.role) or 0) + 1

    link_counts = card.setdefault('link_counts', {})
    for bucket, urls in (enrichment.links or {}).items():
        if urls:
            link_counts[bucket] = int(link_counts.get(bucket) or 0) + len(urls)

    vids = card.setdefault('video_ids', [])
    if enrichment.video_id not in vids:
        vids.append(enrichment.video_id)
        # Cap stored ids so channel cards stay small
        if len(vids) > 200:
            card['video_ids'] = vids[-200:]

    if cat_counts:
        card['dominant_category'] = max(cat_counts.items(), key=lambda kv: kv[1])[0]
    if role_counts:
        card['dominant_role'] = max(role_counts.items(), key=lambda kv: kv[1])[0]

    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(card, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    return path


def append_index(
    references_base: str,
    *,
    platform: str,
    key: str,
    status: str,
    detail: str = '',
) -> None:
    """Append one line to enrichment/index.jsonl."""
    ensure_enrichment_dirs(references_base, platform)
    record = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'platform': platform,
        'key': key,
        'status': status,
        'detail': detail,
    }
    with open(index_path(references_base), 'a', encoding='utf-8') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
