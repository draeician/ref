"""Domain normalization and hostname matching for read-only URL dumps."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

_LABEL_RE = re.compile(r'[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?')
_MAX_LABEL_LENGTH = 63
_MAX_DOMAIN_LENGTH = 253

# Characters that mean the caller passed a URL (or junk) instead of a bare domain.
_URL_MARKERS = ('://', '//', '/', '?', '#', '%', '@', ':', ' ', '\t')


def normalize_domain(raw: str) -> str:
    """Validate ``raw`` as a bare domain and return it lowercased.

    Accepts ``example.com``, ``Example.COM``, ``docs.example.com.``, and
    hostnames with internal hyphens/underscores. Rejects empty values, URLs
    (scheme / path / port), single labels such as ``com``, and invalid label
    characters. Raises ``ValueError`` with an operator-facing message so callers
    can report it on stderr or as an HTTP 400.

    Non-ASCII (IDN) domains are not decoded here: pass the punycode form, e.g.
    ``xn--nic-1oa.com``.
    """
    text = (raw or '').strip()
    if not text:
        raise ValueError("Domain must be a non-empty name such as 'example.com'")

    lowered = text.lower()
    if any(marker in lowered for marker in _URL_MARKERS):
        raise ValueError(
            f"Invalid domain {raw!r}. Pass a bare domain like 'example.com' "
            "(no scheme, path, port, or spaces)."
        )

    lowered = lowered.rstrip('.')
    labels = lowered.split('.')
    if len(labels) < 2:
        raise ValueError(
            f"Invalid domain {raw!r}. Use a dotted domain such as 'example.com'."
        )

    for label in labels:
        if not label:
            raise ValueError(f"Invalid domain {raw!r}: empty label between dots.")
        if len(label) > _MAX_LABEL_LENGTH:
            raise ValueError(
                f"Invalid domain {raw!r}: label {label!r} exceeds "
                f"{_MAX_LABEL_LENGTH} characters."
            )
        if not _LABEL_RE.fullmatch(label):
            raise ValueError(
                f"Invalid domain {raw!r}. Labels use letters, digits, '-' or '_',"
                " and may not start or end with '-' or '_'."
            )

    if len(lowered) > _MAX_DOMAIN_LENGTH:
        raise ValueError(
            f"Invalid domain {raw!r}: longer than {_MAX_DOMAIN_LENGTH} characters."
        )

    return lowered


def url_hostname(raw_url: str) -> Optional[str]:
    """Return the lowercased hostname of ``raw_url``, or None when unparsable.

    Scheme-less stored values (``example.com/path``) are parsed as authorities so
    matching never falls back to substring comparison.
    """
    text = (raw_url or '').strip()
    if not text:
        return None

    candidates: List[str] = [text]
    if '//' not in text:
        candidates.append(f'//{text}')

    for candidate in candidates:
        try:
            host = urlparse(candidate).hostname
        except ValueError:  # malformed authority or port
            continue
        if host:
            return host.lower().rstrip('.')
    return None


def hostname_matches(raw_url: str, domain: str) -> bool:
    """True when ``raw_url``'s parsed host is ``domain`` or a subdomain of it.

    ``domain`` must already be normalized (see :func:`normalize_domain`). Host
    comparison is case-insensitive and label-anchored, so ``notexample.com`` and
    ``example.com.evil.net`` do not match ``example.com``.
    """
    host = url_hostname(raw_url)
    if not host:
        return False
    return host == domain or host.endswith(f'.{domain}')
