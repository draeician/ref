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


class StubProvider(RedditProvider):
    """Deterministic provider that returns a fixed result."""

    def __init__(self, result):
        self.result = result
        self.fetched = []

    def fetch_submission(self, object_id):
        self.fetched.append(("submission", object_id))
        return self.result

    def fetch_comment(self, object_id):
        self.fetched.append(("comment", object_id))
        return self.result


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
