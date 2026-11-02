"""Domain normalization and hostname matching for read-only URL dumps."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

_LABEL_RE = re.compile(r'[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?')
_MAX_LABEL_LENGTH = 63
_MAX_DOMAIN_LENGTH = 253

# Characters that mean the caller passed a URL (or junk) instead of a bare domain.
_URL_MARKERS = ('://', '//', '/', '?', '#', '%', '@', ':', ' ', '\t')

# Leading ``scheme:`` (optionally followed by ``//``). Group 2 records hierarchy.
_SCHEME_RE = re.compile(r'^([a-z][a-z0-9+.-]*):(//)?', re.IGNORECASE)

# Schemes that never carry a web authority, even when written with slashes.
_NON_WEB_SCHEMES = frozenset(
    {
        'about',
        'blob',
        'data',
        'javascript',
        'mailto',
        'magnet',
        'sms',
        'tel',
        'urn',
    }
)


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
    matching never falls back to substring comparison. Only a leading scheme, or a
    leading ``//``, decides whether the value is hierarchical; ``//`` that appears
    later — inside a path such as ``example.com/foo//bar`` or inside a query such
    as ``example.com/path?q=https://other.com`` — stays in the path/query and never
    suppresses authority parsing.

    Non-web URIs are not treated as hostnames: opaque schemes (``mailto:``,
    ``data:``, ``tel:``, ``urn:`` …) return None, and an email address such as
    ``user@example.com`` is rejected because a stored value without its own scheme
    has no userinfo to separate from the authority. Credentials on a real URL
    (``https://user:pw@sub.example.com/``) still resolve normally.
    """
    text = (raw_url or '').strip()
    if not text:
        return None

    scheme_match = _SCHEME_RE.match(text)
    scheme = scheme_match.group(1).lower() if scheme_match else ''
    has_scheme_authority = bool(scheme_match and scheme_match.group(2))

    if scheme in _NON_WEB_SCHEMES:
        return None
    # ``token:`` with no slashes is an opaque scheme (``mailto:x``, ``urn:x``) unless
    # the token itself looks like a host, e.g. scheme-less ``example.com:8443/path``.
    if scheme and not has_scheme_authority and '.' not in scheme:
        return None

    candidate = text if (has_scheme_authority or text.startswith('//')) else f'//{text}'
    try:
        parsed = urlsplit(candidate)
        host = parsed.hostname  # ValueError on a malformed authority or port
    except ValueError:
        return None

    if not has_scheme_authority and '@' in parsed.netloc:
        return None  # an email address, not a stored web URL
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
