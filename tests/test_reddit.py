"""Tests for the Reddit provider, URL parsing, and outbound link discovery."""

from __future__ import annotations

import requests

from ref_cli.reddit import (
    ArcticShiftProvider,
    RedditContent,
    RedditProvider,
    discover_outbound_urls,
    fetch_reddit_content,
    is_reddit_url,
    parse_reddit_url,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, json_exc=None):
        self.status_code = status_code
        self._payload = payload
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


class FakeSession:
    """Minimal requests.Session stand-in for ArcticShiftProvider tests."""

    def __init__(self, status_code=200, payload=None, exc=None, json_exc=None):
        self.status_code = status_code
        self.payload = payload
        self.exc = exc
        self.json_exc = json_exc
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if self.exc is not None:
            raise self.exc
        return FakeResponse(self.status_code, self.payload, self.json_exc)


class RoutingSession:
    """Returns a different FakeResponse per endpoint (matched by URL substring)."""

    def __init__(self, routes):
        # routes: dict of url substring -> (status_code, payload, json_exc)
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        for key, spec in self.routes.items():
            if key in url:
                status_code, payload, json_exc = spec
                return FakeResponse(status_code, payload, json_exc)
        return FakeResponse(200, {"data": []})


class StubProvider(RedditProvider):
    """Deterministic provider that returns a fixed result."""

    def __init__(self, result, comments=None):
        self.result = result
        self.comments = list(comments) if comments is not None else []
        self.fetched = []

    def fetch_submission(self, object_id):
        self.fetched.append(("submission", object_id))
        return self.result

    def fetch_comment(self, object_id):
        self.fetched.append(("comment", object_id))
        return self.result

    def fetch_submission_comments(self, submission_id):
        self.fetched.append(("comments", submission_id))
        return list(self.comments)


# ---------------------------------------------------------------------------
# URL recognition / parsing
# ---------------------------------------------------------------------------


def test_is_reddit_url():
    assert is_reddit_url("https://www.reddit.com/r/test/comments/abc123/slug/")
    assert is_reddit_url("https://redd.it/abc123")
    assert is_reddit_url("https://old.reddit.com/r/test/comments/abc/slug/")
    assert is_reddit_url("https://np.reddit.com/r/x")
    assert not is_reddit_url("https://example.com/r/test")
    assert not is_reddit_url("https://reddit.example.com/fake")


def test_parse_submission_url():
    ref = parse_reddit_url("https://www.reddit.com/r/test/comments/abc123/slug/")
    assert ref is not None
    assert ref.kind == "submission"
    assert ref.submission_id == "abc123"
    assert ref.comment_id == ""


def test_parse_submission_without_subreddit():
    ref = parse_reddit_url("https://www.reddit.com/comments/abc123/slug/")
    assert ref is not None
    assert ref.kind == "submission"
    assert ref.submission_id == "abc123"


def test_parse_submission_short_url():
    ref = parse_reddit_url("https://redd.it/abc123")
    assert ref is not None
    assert ref.kind == "submission"
    assert ref.submission_id == "abc123"


def test_parse_comment_url():
    ref = parse_reddit_url("https://www.reddit.com/r/test/comments/abc123/slug/def456/")
    assert ref is not None
    assert ref.kind == "comment"
    assert ref.submission_id == "abc123"
    assert ref.comment_id == "def456"


def test_parse_old_reddit_host():
    ref = parse_reddit_url("https://old.reddit.com/r/test/comments/abc123/slug/")
    assert ref is not None
    assert ref.kind == "submission"


def test_parse_non_reddit_returns_none():
    assert parse_reddit_url("https://example.com/r/test/comments/abc123/") is None
    assert parse_reddit_url("https://www.reddit.com/r/test/abc123/") is None
    assert parse_reddit_url("not a url") is None


# ---------------------------------------------------------------------------
# Provider (Arctic Shift)
# ---------------------------------------------------------------------------


def test_provider_submission_success():
    payload = {
        "data": [
            {
                "id": "1a2b3c",
                "name": "t3_1a2b3c",
                "selftext": (
                    "check [example](https://example.com/article) and "
                    "https://github.com/a/b"
                ),
                "title": "My post",
                "subreddit": "test",
            }
        ]
    }
    session = FakeSession(payload=payload)
    provider = ArcticShiftProvider(session=session)
    result = provider.fetch_submission("1a2b3c")

    assert result.found
    assert result.kind == "submission"
    assert result.title == "My post"
    assert result.subreddit == "test"
    assert "https://example.com/article" in result.urls
    assert "https://github.com/a/b" in result.urls
    assert session.calls and session.calls[0][0].endswith("/api/posts/ids")


def test_provider_comment_success():
    payload = {
        "data": [
            {
                "id": "def456",
                "name": "t1_def456",
                "body": "also see https://example.com/other",
                "subreddit": "test",
                "link_id": "t3_1a2b3c",
            }
        ]
    }
    provider = ArcticShiftProvider(session=FakeSession(payload=payload))
    result = provider.fetch_comment("def456")

    assert result.found
    assert result.kind == "comment"
    assert result.text == "also see https://example.com/other"
    assert result.urls == ["https://example.com/other"]


def _link_submission_payload(**fields) -> dict:
    base = {
        "id": "abc123",
        "name": "t3_abc123",
        "selftext": "",
        "title": "A link post",
        "subreddit": "test",
    }
    base.update(fields)
    return {"data": [base]}


def test_link_submission_destination_discovered():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                url="https://example.com/article",
                url_overridden_by_dest="https://example.com/article",
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/article"]


def test_link_submission_destination_and_selftext():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                selftext="see https://selftext.example/extra",
                url="https://example.com/article",
                url_overridden_by_dest="https://example.com/article",
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/article", "https://selftext.example/extra"]


def test_link_submission_duplicate_destination_deduped():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                selftext="https://example.com/article",
                url="https://example.com/article",
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/article"]


def test_link_submission_reddit_destination_filtered():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                url="https://www.reddit.com/r/other/comments/xyz/slug/"
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == []


def test_link_submission_missing_destination_uses_selftext():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                selftext="check https://example.com/from-text"
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/from-text"]


def test_link_submission_prefers_url_overridden_by_dest():
    provider = ArcticShiftProvider(
        session=FakeSession(
            payload=_link_submission_payload(
                url="https://example.com/original",
                url_overridden_by_dest="https://example.com/canonical",
            )
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/canonical"]


def test_provider_archive_miss_is_not_found():
    provider = ArcticShiftProvider(session=FakeSession(payload={"data": []}))
    result = provider.fetch_submission("zzzzzz")
    assert not result.found
    assert result.status == "not_found"


def test_provider_http_error_is_unavailable():
    provider = ArcticShiftProvider(session=FakeSession(status_code=500, payload={}))
    result = provider.fetch_submission("abc123")
    assert not result.found
    assert result.status == "unavailable"


def test_provider_network_failure_is_unavailable():
    provider = ArcticShiftProvider(
        session=FakeSession(exc=requests.ConnectionError("boom"))
    )
    result = provider.fetch_submission("abc123")
    assert not result.found
    assert result.status == "unavailable"


def test_provider_malformed_json_is_error():
    provider = ArcticShiftProvider(
        session=FakeSession(json_exc=ValueError("bad json"))
    )
    result = provider.fetch_submission("abc123")
    assert not result.found
    assert result.status == "error"


def test_provider_unexpected_shape_is_error():
    # JSON decodes but is not the expected {"data": [...]} shape.
    provider = ArcticShiftProvider(session=FakeSession(payload={"unexpected": True}))
    result = provider.fetch_submission("abc123")
    assert result.status == "error"


def test_archive_miss_does_not_imply_deletion():
    provider = StubProvider(
        RedditContent(status="not_found", kind="submission", object_id="abc123")
    )
    result = fetch_reddit_content(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert not result.found
    assert result.status == "not_found"
    # Absence is never labeled as deletion/removal.
    assert "deleted" not in result.status
    assert "removed" not in result.status


# ---------------------------------------------------------------------------
# Outbound link discovery
# ---------------------------------------------------------------------------


def test_discover_outbound_urls_filters_reddit_and_dedupes():
    provider = StubProvider(
        RedditContent(
            status="found",
            kind="submission",
            object_id="abc123",
            text="",
            urls=[
                "https://example.com/a",
                "https://github.com/b/c",
                "https://www.reddit.com/r/other/comments/xyz/slug/",
                "https://example.com/a",
            ],
        )
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/a", "https://github.com/b/c"]


def test_discover_outbound_urls_miss_returns_empty():
    provider = StubProvider(RedditContent(status="not_found"))
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == []


def test_fetch_reddit_content_routes_comment():
    provider = StubProvider(
        RedditContent(status="found", kind="comment", object_id="def456")
    )
    result = fetch_reddit_content(
        "https://www.reddit.com/r/test/comments/abc123/slug/def456/", provider=provider
    )
    assert result.found
    assert provider.fetched == [("comment", "def456")]


def test_fetch_reddit_content_non_reddit_url_is_error():
    result = fetch_reddit_content("https://example.com/x")
    assert result.status == "error"
    assert not result.found


# ---------------------------------------------------------------------------
# Comment-tree retrieval (Arctic Shift) and comment-link discovery
# ---------------------------------------------------------------------------


def _comment_node(body=None, cid="c1", replies=None):
    data = {
        "id": cid,
        "name": f"t1_{cid}",
        "body": body,
        "subreddit": "test",
        "link_id": "t3_abc123",
    }
    if replies is not None:
        data["replies"] = replies
    return {"kind": "t1", "data": data}


def _more_node(child_ids, cid="m1"):
    return {
        "kind": "more",
        "data": {"count": len(child_ids), "id": cid, "children": list(child_ids)},
    }


def _listing(children):
    return {"kind": "Listing", "data": {"children": children}}


def _tree_payload(nodes):
    return {"data": nodes}


def test_comment_tree_fetches_top_level_comment_link():
    provider = StubProvider(
        RedditContent(status="found", kind="submission", object_id="abc123", urls=[]),
        comments=["see https://github.com/a/b in a comment"],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://github.com/a/b"]


def test_comment_tree_nested_reply_body_collected():
    tree = [
        _comment_node(
            body="top level no link",
            cid="c1",
            replies=_listing(
                [
                    _comment_node(
                        body="nested reply https://github.com/nested/link",
                        cid="c2",
                        replies="",
                    )
                ]
            ),
        )
    ]
    provider = ArcticShiftProvider(session=FakeSession(payload=_tree_payload(tree)))
    bodies = provider.fetch_submission_comments("abc123")
    assert bodies == [
        "top level no link",
        "nested reply https://github.com/nested/link",
    ]


def test_multiple_comments_multiple_links():
    provider = StubProvider(
        RedditContent(status="found", kind="submission", object_id="abc123", urls=[]),
        comments=[
            "first https://a.example/1",
            "second https://b.example/2 and https://c.example/3",
        ],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://a.example/1", "https://b.example/2", "https://c.example/3"]


def test_duplicate_submission_and_comment_url_deduped():
    provider = StubProvider(
        RedditContent(
            status="found",
            kind="submission",
            object_id="abc123",
            urls=["https://example.com/a"],
        ),
        comments=["see https://example.com/a again"],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/a"]


def test_duplicate_comment_url_deduped():
    provider = StubProvider(
        RedditContent(status="found", kind="submission", object_id="abc123", urls=[]),
        comments=["https://example.com/a", "also https://example.com/a"],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/a"]


def test_reddit_url_in_comment_filtered():
    provider = StubProvider(
        RedditContent(status="found", kind="submission", object_id="abc123", urls=[]),
        comments=[
            "https://www.reddit.com/r/other/comments/xyz/slug/ and https://example.com/a"
        ],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/a"]


def test_comment_tree_http_failure_keeps_submission_urls():
    routes = {
        "/api/posts/ids": (
            200,
            {
                "data": [
                    {
                        "id": "abc123",
                        "name": "t3_abc123",
                        "selftext": "https://example.com/sub",
                        "title": "t",
                        "subreddit": "test",
                    }
                ]
            },
            None,
        ),
        "/api/comments/tree": (500, {}, None),
    }
    provider = ArcticShiftProvider(session=RoutingSession(routes))
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/sub"]


def test_comment_tree_malformed_response_keeps_submission_urls():
    routes = {
        "/api/posts/ids": (
            200,
            {
                "data": [
                    {
                        "id": "abc123",
                        "name": "t3_abc123",
                        "selftext": "https://example.com/sub",
                        "title": "t",
                        "subreddit": "test",
                    }
                ]
            },
            None,
        ),
        "/api/comments/tree": (200, {"unexpected": True}, None),
    }
    provider = ArcticShiftProvider(session=RoutingSession(routes))
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/sub"]


def test_comment_tree_malformed_json_keeps_submission_urls():
    routes = {
        "/api/posts/ids": (
            200,
            {
                "data": [
                    {
                        "id": "abc123",
                        "name": "t3_abc123",
                        "selftext": "https://example.com/sub",
                        "title": "t",
                        "subreddit": "test",
                    }
                ]
            },
            None,
        ),
        "/api/comments/tree": (200, None, ValueError("bad json")),
    }
    provider = ArcticShiftProvider(session=RoutingSession(routes))
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/", provider=provider
    )
    assert urls == ["https://example.com/sub"]


def test_comment_tree_more_node_ignored():
    tree = [
        _comment_node(body="real comment https://example.com/real", cid="c1", replies=""),
        _more_node(["c2"]),
    ]
    provider = ArcticShiftProvider(session=FakeSession(payload=_tree_payload(tree)))
    bodies = provider.fetch_submission_comments("abc123")
    assert bodies == ["real comment https://example.com/real"]


def test_comment_tree_nested_more_node_ignored():
    tree = [
        _comment_node(
            body="top",
            cid="c1",
            replies=_listing([_more_node(["c2"])]),
        )
    ]
    provider = ArcticShiftProvider(session=FakeSession(payload=_tree_payload(tree)))
    bodies = provider.fetch_submission_comments("abc123")
    assert bodies == ["top"]


def test_comment_tree_ignores_missing_or_nonstring_body():
    tree = [
        _comment_node(body="good https://example.com/good", cid="c1", replies=""),
        {"kind": "t1", "data": {"id": "c2"}},
        {"kind": "t1", "data": {"id": "c3", "body": 12345}},
        {"kind": "t1", "data": {"id": "c4", "body": "   "}},
    ]
    provider = ArcticShiftProvider(session=FakeSession(payload=_tree_payload(tree)))
    bodies = provider.fetch_submission_comments("abc123")
    assert bodies == ["good https://example.com/good"]


def test_direct_comment_url_does_not_fetch_tree():
    provider = StubProvider(
        RedditContent(
            status="found",
            kind="comment",
            object_id="def456",
            urls=["https://example.com/from-comment"],
        ),
        comments=["https://example.com/should-not-appear"],
    )
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/test/comments/abc123/slug/def456/", provider=provider
    )
    assert urls == ["https://example.com/from-comment"]
    assert provider.fetched == [("comment", "def456")]


def test_real_world_comment_tree_regression_1wlhwmi():
    """The submission carries no outbound link; only a comment has the GitHub URL."""
    tree = [
        _comment_node(
            body=(
                "Here is the GitHub for my playwright like system:\n\n"
                "https://github.com/VISNRY-ENTERTAINMENT/Human-ScreenVision-Open"
            ),
            cid="payuk1x",
            replies="",
        )
    ]
    routes = {
        "/api/posts/ids": (
            200,
            {
                "data": [
                    {
                        "id": "1wlhwmi",
                        "name": "t3_1wlhwmi",
                        "selftext": "",
                        "title": "anyone want to test my playwright inspired screen",
                        "subreddit": "vibecoding",
                    }
                ]
            },
            None,
        ),
        "/api/comments/tree": (200, {"data": tree}, None),
    }
    provider = ArcticShiftProvider(session=RoutingSession(routes))
    urls = discover_outbound_urls(
        "https://www.reddit.com/r/vibecoding/comments/1wlhwmi/"
        "anyone_want_to_test_my_playwright_inspired_screen/",
        provider=provider,
    )
    assert urls == [
        "https://github.com/VISNRY-ENTERTAINMENT/Human-ScreenVision-Open"
    ]


def test_process_url_reddit_discovers_and_processes_outbound(monkeypatch, tmp_path):
    """Capturing a Reddit URL records it and feeds outbound links to process_url."""
    from ref_cli import cli

    reddit_url = "https://www.reddit.com/r/test/comments/abc123/slug/"
    references_file = tmp_path / "references.md"
    references_file.write_text("")

    monkeypatch.setattr(cli, "UNIFIED", str(references_file))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)

    recorded = []

    def fake_record_general(url, force, current_time):
        recorded.append(("general", url))

    monkeypatch.setattr(cli, "_record_general_url", fake_record_general)
    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls",
        lambda url: ["https://example.com/out"],
    )

    real_process_url = cli.process_url
    outbound_calls = []

    def fake_process_url(url, force=False):
        if url == reddit_url:
            return real_process_url(url, force)
        outbound_calls.append(url)

    monkeypatch.setattr(cli, "process_url", fake_process_url)

    cli.process_url(reddit_url, force=False)

    assert ("general", reddit_url) in recorded
    assert outbound_calls == ["https://example.com/out"]


def test_process_url_comment_link_flows_to_process_url(monkeypatch, tmp_path):
    """A URL discovered only in a comment is fed into the normal process_url path."""
    from ref_cli import cli
    from ref_cli.reddit import discover_outbound_urls as real_discover

    reddit_url = "https://www.reddit.com/r/test/comments/abc123/slug/"
    references_file = tmp_path / "references.md"
    references_file.write_text("")

    monkeypatch.setattr(cli, "UNIFIED", str(references_file))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)
    monkeypatch.setattr(cli, "_record_general_url", lambda *a, **k: None)

    stub = StubProvider(
        RedditContent(status="found", kind="submission", object_id="abc123", urls=[]),
        comments=["see https://github.com/comment/link"],
    )
    monkeypatch.setattr(
        "ref_cli.reddit.discover_outbound_urls",
        lambda url: real_discover(url, provider=stub),
    )

    real_process_url = cli.process_url
    outbound_calls = []

    def fake_process_url(url, force=False):
        if url == reddit_url:
            return real_process_url(url, force)
        outbound_calls.append(url)

    monkeypatch.setattr(cli, "process_url", fake_process_url)

    cli.process_url(reddit_url, force=False)

    assert outbound_calls == ["https://github.com/comment/link"]


def test_process_url_reddit_miss_continues_without_crash(monkeypatch, tmp_path):
    """A Reddit archive miss must not fail the surrounding capture operation."""
    from ref_cli import cli

    reddit_url = "https://www.reddit.com/r/test/comments/abc123/slug/"
    references_file = tmp_path / "references.md"
    references_file.write_text("")

    monkeypatch.setattr(cli, "UNIFIED", str(references_file))
    monkeypatch.setattr(cli, "resolve_redirect", lambda url: url)
    monkeypatch.setattr(cli, "simplify_url", lambda url: url)
    monkeypatch.setattr(cli, "_record_general_url", lambda *a, **k: None)
    monkeypatch.setattr("ref_cli.reddit.discover_outbound_urls", lambda url: [])

    # Should not raise even though no outbound links were discovered.
    cli.process_url(reddit_url, force=False)
