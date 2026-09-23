"""Reddit content retrieval for link discovery (Arctic Shift archive first).

Reddit is a *link-discovery* input source: we fetch submission/comment text to
discover outbound URLs, then hand those URLs to the normal archive/enrichment
pipeline (``ref``'s ``process_url``). No Reddit-specific archive silo is
created here.

An archive miss (Arctic Shift returns no object) means only *not found*,
*unavailable from that provider*, or *unknown* — it never implies the Reddit
object was deleted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from ref_cli.enrichment import extract_urls

ARCTIC_SHIFT_BASE = "https://arctic-shift.photon-reddit.com"

# Number of top-level comments to pull for link discovery. Large enough to
# cover a normal-sized thread, small enough to avoid an unbounded request.
_COMMENT_TREE_LIMIT = 100

_REDDIT_HOSTS = ("reddit.com", "redd.it")


def is_reddit_url(url: str) -> bool:
    """Return True when *url* is a reddit.com or redd.it host."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == h or host.endswith("." + h) for h in _REDDIT_HOSTS)


@dataclass
class RedditReference:
    """A Reddit object located by a URL: a submission or a comment."""

    kind: str  # 'submission' | 'comment'
    submission_id: str = ""
    comment_id: str = ""


def parse_reddit_url(url: str) -> Optional[RedditReference]:
    """Resolve a Reddit URL into a submission/comment reference.

    Handles the common shapes:
      - ``reddit.com/r/<sub>/comments/<id>/<slug>/``          → submission
      - ``reddit.com/comments/<id>/<slug>/``                  → submission
      - ``reddit.com/r/<sub>/comments/<id>/<slug>/<cid>/``    → comment
      - ``redd.it/<id>``                                      → submission

    Returns ``None`` for non-Reddit URLs or shapes that don't locate an object.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None

    if host == "redd.it" or host.endswith(".redd.it"):
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            return None
        return RedditReference(kind="submission", submission_id=parts[0])

    if not (host == "reddit.com" or host.endswith(".reddit.com")):
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if "comments" not in parts:
        return None
    idx = parts.index("comments")
    if idx + 1 >= len(parts):
        return None
    submission_id = parts[idx + 1]
    # Segments after `comments`: <submission_id>, <slug>, [<comment_id>]
    if idx + 3 < len(parts):
        return RedditReference(
            kind="comment",
            submission_id=submission_id,
            comment_id=parts[idx + 3],
        )
    return RedditReference(kind="submission", submission_id=submission_id)


@dataclass
class RedditContent:
    """Normalized result of a Reddit content fetch.

    ``status`` is one of:
      - ``found``       — object retrieved, ``text``/``urls`` populated
      - ``not_found``   — archive has no object for the id (never "deleted")
      - ``unavailable`` — network/rate-limit/server failure (transient)
      - ``error``       — malformed response or unexpected shape
    """

    status: str
    kind: str = ""  # 'submission' | 'comment' | ''
    object_id: str = ""
    subreddit: str = ""
    title: str = ""
    text: str = ""
    urls: List[str] = field(default_factory=list)
    detail: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def found(self) -> bool:
        return self.status == "found"


class RedditProvider:
    """Minimal transport boundary for Reddit submission/comment content.

    Provider/API details live behind this interface so enrichment and capture
    logic never see Arctic Shift (or a future live provider) directly.
    """

    def fetch_submission(self, object_id: str) -> RedditContent:
        raise NotImplementedError

    def fetch_comment(self, object_id: str) -> RedditContent:
        raise NotImplementedError

    def fetch_submission_comments(self, submission_id: str) -> List[str]:
        """Return archived comment bodies for a submission (best-effort).

        Defaults to an empty list so providers without comment-tree support
        contribute no comment links.
        """
        return []


# Submission fields that carry the explicit outbound destination for link posts,
# in preference order. ``url_overridden_by_dest`` is the canonical external
# target after Reddit's redirect; ``url`` is the raw submitted destination.
_SUBMISSION_DESTINATION_FIELDS = ("url_overridden_by_dest", "url")


def _submission_destination(obj: Dict[str, Any]) -> str:
    """Return a link submission's external destination URL, or ``""``.

    Prefers ``url_overridden_by_dest`` over ``url`` and returns ``""`` when the
    fields are absent, malformed, or not an absolute http(s) URL (e.g. a Reddit
    self/permalink link for text posts is still http, so callers filter those).
    """
    for key in _SUBMISSION_DESTINATION_FIELDS:
        value = obj.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value.startswith(("http://", "https://")):
                return value
    return ""


class ArcticShiftProvider(RedditProvider):
    """Retrieve Reddit objects from the Arctic Shift archive API."""

    def __init__(
        self,
        *,
        base_url: str = ARCTIC_SHIFT_BASE,
        session: Optional[requests.Session] = None,
        timeout: float = 15.0,
    ) -> None:
        self.base_url = (base_url or ARCTIC_SHIFT_BASE).rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def fetch_submission(self, object_id: str) -> RedditContent:
        return self._fetch("posts", object_id, kind="submission")

    def fetch_comment(self, object_id: str) -> RedditContent:
        return self._fetch("comments", object_id, kind="comment")

    def fetch_submission_comments(self, submission_id: str) -> List[str]:
        """Fetch the archived comment tree for a submission (best-effort).

        Returns the list of comment bodies (in traversal order) found under the
        submission. Never raises: any transport/parse failure logs and yields an
        empty list so submission capture is unaffected.
        """
        url = f"{self.base_url}/api/comments/tree"
        params = {"link_id": f"t3_{submission_id}", "limit": _COMMENT_TREE_LIMIT}
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            logging.info(
                "Arctic Shift comment tree request failed for %s: %s",
                submission_id,
                exc,
            )
            return []

        if response.status_code == 429:
            logging.info(
                "Arctic Shift comment tree rate limited for %s (HTTP 429)",
                submission_id,
            )
            return []
        if response.status_code >= 500:
            logging.info(
                "Arctic Shift comment tree server error for %s (HTTP %s)",
                submission_id,
                response.status_code,
            )
            return []
        if response.status_code != 200:
            logging.info(
                "Arctic Shift comment tree returned HTTP %s for %s",
                response.status_code,
                submission_id,
            )
            return []

        try:
            payload = response.json()
        except ValueError:
            logging.info(
                "Arctic Shift comment tree malformed JSON for %s", submission_id
            )
            return []

        if not isinstance(payload, dict):
            logging.info(
                "Arctic Shift comment tree unexpected shape for %s", submission_id
            )
            return []

        data = payload.get("data")
        if not isinstance(data, list):
            logging.info(
                "Arctic Shift comment tree unexpected shape for %s", submission_id
            )
            return []

        bodies: List[str] = []
        for node in data:
            _walk_comment_tree(node, bodies)
        return bodies

    def _fetch(self, collection: str, object_id: str, kind: str) -> RedditContent:
        url = f"{self.base_url}/api/{collection}/ids"
        try:
            response = self.session.get(
                url,
                params={"ids": object_id},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logging.info("Arctic Shift request failed for %s: %s", object_id, exc)
            return RedditContent(
                status="unavailable",
                kind=kind,
                object_id=object_id,
                detail=f"request failed: {exc}",
            )

        if response.status_code == 429:
            return RedditContent(
                status="unavailable",
                kind=kind,
                object_id=object_id,
                detail="rate limited (HTTP 429)",
            )
        if response.status_code >= 500:
            return RedditContent(
                status="unavailable",
                kind=kind,
                object_id=object_id,
                detail=f"server error (HTTP {response.status_code})",
            )
        if response.status_code != 200:
            return RedditContent(
                status="error",
                kind=kind,
                object_id=object_id,
                detail=f"HTTP {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError:
            return RedditContent(
                status="error",
                kind=kind,
                object_id=object_id,
                detail="malformed JSON response",
            )
        if not isinstance(payload, dict):
            return RedditContent(
                status="error",
                kind=kind,
                object_id=object_id,
                detail="unexpected response shape",
            )

        data = payload.get("data")
        if not isinstance(data, list):
            return RedditContent(
                status="error",
                kind=kind,
                object_id=object_id,
                detail="unexpected response shape",
            )
        if not data:
            # Archive miss: not found / unavailable from this provider / unknown.
            return RedditContent(
                status="not_found",
                kind=kind,
                object_id=object_id,
                detail="no archived object for id",
            )

        obj = data[0]
        if not isinstance(obj, dict):
            return RedditContent(
                status="error",
                kind=kind,
                object_id=object_id,
                detail="unexpected object shape",
            )
        return self._build(kind, object_id, obj)

    @staticmethod
    def _build(kind: str, object_id: str, obj: Dict[str, Any]) -> RedditContent:
        if kind == "submission":
            text = obj.get("selftext") or ""
            title = obj.get("title") or ""
        else:
            text = obj.get("body") or ""
            title = ""

        urls: List[str] = []
        seen = set()

        if kind == "submission":
            # Link posts carry their outbound destination on the object; prefer
            # it so an empty selftext still yields the URL this feature exists
            # to discover. Reddit self/permalink URLs are filtered here (and
            # again in discover_outbound_urls) to keep Reddit→Reddit recursion
            # bounded.
            destination = _submission_destination(obj)
            if destination and not is_reddit_url(destination):
                urls.append(destination)
                seen.add(destination)

        for candidate in extract_urls(text):
            if candidate in seen:
                continue
            seen.add(candidate)
            urls.append(candidate)

        return RedditContent(
            status="found",
            kind=kind,
            object_id=object_id,
            subreddit=obj.get("subreddit") or "",
            title=title,
            text=text,
            urls=urls,
            raw=obj,
        )


def _walk_comment_tree(node: Any, bodies: List[str]) -> None:
    """Recursively collect usable comment bodies from an Arctic Shift tree node.

    Traverses ``t1`` comment nodes in first-seen order, descending into nested
    ``replies``. Non-comment nodes (``more`` placeholders and anything else) and
    comments without a usable string body are skipped safely.
    """
    if not isinstance(node, dict):
        return
    if node.get("kind") != "t1":
        return

    data = node.get("data")
    if not isinstance(data, dict):
        return

    body = data.get("body")
    if isinstance(body, str) and body.strip():
        bodies.append(body)

    replies = data.get("replies")
    if isinstance(replies, dict):
        listing = replies.get("data")
        if isinstance(listing, dict):
            children = listing.get("children")
            if isinstance(children, list):
                for child in children:
                    _walk_comment_tree(child, bodies)


def fetch_reddit_content(
    url: str,
    provider: Optional[RedditProvider] = None,
) -> RedditContent:
    """Fetch the Reddit object referenced by *url* from the given provider."""
    ref = parse_reddit_url(url)
    if ref is None:
        return RedditContent(status="error", detail="not a Reddit object URL")
    provider = provider or ArcticShiftProvider()
    if ref.kind == "comment":
        return provider.fetch_comment(ref.comment_id)
    return provider.fetch_submission(ref.submission_id)


def discover_outbound_urls(
    url: str,
    provider: Optional[RedditProvider] = None,
) -> List[str]:
    """Fetch Reddit content and return outbound (non-Reddit) URLs found in it.

    Never raises: provider/network failures log and return an empty list so the
    surrounding archive operation continues. A miss is reported as *not found*,
    never as deletion.
    """
    provider = provider or ArcticShiftProvider()
    result = fetch_reddit_content(url, provider=provider)
    if not result.found:
        logging.info(
            "Reddit content not retrieved (%s): %s",
            result.status,
            result.detail or "no detail",
        )
        return []

    outbound: List[str] = []
    seen = set()
    for candidate in result.urls:
        if is_reddit_url(candidate):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        outbound.append(candidate)

    # For submissions, also discover links in the archived comment tree. This
    # is best-effort enrichment: any comment-fetch failure logs and yields an
    # empty body list, leaving submission-level URLs intact.
    if result.kind == "submission":
        for body in provider.fetch_submission_comments(result.object_id):
            for candidate in extract_urls(body):
                if is_reddit_url(candidate):
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                outbound.append(candidate)

    return outbound
