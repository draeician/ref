"""List URLs from references.md (last-N or duration window)."""

from __future__ import annotations

import os
import re
from collections import deque
from datetime import datetime, timedelta
from typing import List, Optional

from ref_cli.references_format import iter_data_rows

_LIST_DURATION_RE = re.compile(
    r"^\s*(\d+)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\s*$",
    re.IGNORECASE,
)


def parse_list_duration(spec: str) -> timedelta:
    """Parse a human duration like ``5 min``, ``1h``, or ``2 days``."""
    match = _LIST_DURATION_RE.match(spec)
    if not match:
        raise ValueError(
            f"Invalid list duration {spec!r}. "
            'Use forms like "5 min", "1 hour", "2d", or "1h".'
        )
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit in ("m", "min", "mins", "minute", "minutes"):
        return timedelta(minutes=amount)
    if unit in ("h", "hr", "hrs", "hour", "hours"):
        return timedelta(hours=amount)
    return timedelta(days=amount)


def list_urls(
    *,
    limit: Optional[int] = None,
    since: Optional[timedelta] = None,
    file_path: str,
) -> List[str]:
    """Return URLs from the archive: last ``limit`` and/or within ``since``."""
    if not os.path.isfile(file_path):
        return []

    if limit is not None:
        if limit < 0:
            raise ValueError(f"List limit must be non-negative, got {limit}")
        if limit == 0:
            return []
        recent = deque(maxlen=limit)
        for row in iter_data_rows(file_path):
            recent.append(row)
        rows = list(reversed(recent))
    else:
        rows = list(iter_data_rows(file_path))

    if since is not None:
        cutoff = datetime.now() - since
        filtered = []
        for row in rows:
            try:
                ts = datetime.fromisoformat(row.timestamp)
            except ValueError:
                continue
            if ts >= cutoff:
                filtered.append(row)
        rows = sorted(filtered, key=lambda r: r.timestamp, reverse=True)

    return [row.url for row in rows]
