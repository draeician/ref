"""Tests for get_title_from_url site-specific title extraction.

Covers generic pages, X/Twitter (meta tags, profile/noscript placeholders,
oEmbed fallback), and Reddit (verification placeholders, oEmbed fallback).
"""

import subprocess

import requests

from ref_cli import cli


def _patch_subprocess(monkeypatch, html):
    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:2] == ['which', 'lynx']:
            return subprocess.CompletedProcess(cmd, 0, '', '')
        if isinstance(cmd, str) and 'lynx' in cmd:
            return subprocess.CompletedProcess(cmd, 0, html, '')
        raise AssertionError('unexpected subprocess.run: %r' % (cmd,))

    monkeypatch.setattr(cli.subprocess, 'run', fake_run)


def test_x_com_og_title(monkeypatch):
    html = '<html><head><meta property="og:title" content="Post from OG"/></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://x.com/user/status/1') == 'Post from OG'


def test_x_com_twitter_name_title(monkeypatch):
    html = '<html><head><meta name="twitter:title" content="Via name attr"/></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://x.com/user/status/2') == 'Via name attr'


def test_x_com_twitter_property_title(monkeypatch):
    html = '<html><head><meta property="twitter:title" content="Via property attr"/></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://x.com/user/status/3') == 'Via property attr'


def test_x_com_og_title_beats_useless_title_tag(monkeypatch):
    html = (
        '<html><head><title>X</title>'
        '<meta property="og:title" content="Real headline"/>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://x.com/user/status/4') == 'Real headline'


def test_x_com_bare_title_x_returns_no_title(monkeypatch):
    html = '<html><head><title>X</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://x.com/user/status/5') == 'No title found'


def test_twitter_com_host_same_as_x(monkeypatch):
    html = '<html><head><meta property="og:title" content="On twitter.com"/></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    assert cli.get_title_from_url('https://twitter.com/i/web/status/9') == 'On twitter.com'


def test_generic_example_com_unchanged(monkeypatch):
    html = '<html><head><title>Hello</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    def boom(*_a, **_k):
        raise AssertionError('requests.get must not run for non-X hosts')

    monkeypatch.setattr(cli.requests, 'get', boom)
    assert cli.get_title_from_url('https://example.com/page') == 'Hello'


def test_x_com_oembed_fallback_when_html_unusable(monkeypatch):
    html = '<html><head><title>X</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'Title from oEmbed API'}

    def fake_get(url, params=None, **_kwargs):
        assert 'publish.twitter.com/oembed' in url
        assert params.get('url', '').startswith('https://x.com/')
        return Resp()

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url('https://x.com/user/status/501') == 'Title from oEmbed API'


def test_x_com_placeholder_og_title_falls_through_to_oembed(monkeypatch):
    html = (
        '<html><head>'
        '<meta property="og:title" content="(JavaScript is not available.)"/>'
        '<title>X</title>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'Real tweet title'}

    monkeypatch.setattr(cli.requests, 'get', lambda *_a, **_k: Resp())
    assert cli.get_title_from_url('https://x.com/i/status/2052093277864612168') == 'Real tweet title'


def test_x_com_placeholder_only_no_oembed_returns_no_title(monkeypatch):
    html = (
        '<html><head>'
        '<meta property="og:title" content="JavaScript is not available."/>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    def fake_get(*_a, **_k):
        raise requests.ConnectionError('unavailable')

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url('https://x.com/user/status/600') == 'No title found'


def test_x_com_og_title_skips_oembed(monkeypatch):
    html = '<html><head><meta property="og:title" content="From HTML"/></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    def boom(*_a, **_k):
        raise AssertionError('oEmbed must not run when HTML meta succeeds')

    monkeypatch.setattr(cli.requests, 'get', boom)
    assert cli.get_title_from_url('https://x.com/user/status/502') == 'From HTML'


def test_x_com_oembed_empty_title_uses_blockquote_html(monkeypatch):
    html = '<html><head><title>X</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                'title': '',
                'html': '<blockquote class="twitter-tweet"><p>Hello from blockquote</p></blockquote>',
            }

    monkeypatch.setattr(cli.requests, 'get', lambda *_a, **_k: Resp())
    assert cli.get_title_from_url('https://x.com/user/status/503') == 'Hello from blockquote'


def test_twitter_com_uses_oembed_with_same_url_param(monkeypatch):
    html = '<html><head><title>X</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    seen = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'oEmbed ok'}

    def fake_get(url, params=None, **_kwargs):
        seen['tweet_url'] = params.get('url')
        return Resp()

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    tweet = 'https://twitter.com/example/status/777'
    assert cli.get_title_from_url(tweet) == 'oEmbed ok'
    assert seen['tweet_url'] == tweet


def test_x_com_oembed_failure_returns_no_title(monkeypatch):
    html = '<html><head><title>X</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    def fake_get(*_a, **_k):
        raise requests.ConnectionError('no network')

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url('https://x.com/user/status/504') == 'No title found'


def test_x_com_profile_og_title_falls_through_to_oembed(monkeypatch):
    html = (
        '<html><head>'
        '<meta property="og:title" content="GitHub Projects Community (@GithubProjects) on X"/>'
        '<meta name="twitter:title" content="GitHub Projects Community (@GithubProjects) on X"/>'
        '<title>X</title>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                'title': (
                    'CodeNomad wraps OpenCode in a full desktop UI with multi-instance '
                    'workspaces — GitHub Projects Community (@GithubProjects) July 10, 2026'
                ),
            }

    def fake_get(url, params=None, **_kwargs):
        assert 'publish.twitter.com/oembed' in url
        assert params.get('url') == (
            'https://x.com/GithubProjects/status/2075527965958713554'
        )
        return Resp()

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url(
        'https://x.com/GithubProjects/status/2075527965958713554'
    ).startswith('CodeNomad wraps OpenCode')


def test_x_com_profile_og_falls_through_to_quoted_title_tag(monkeypatch):
    html = (
        '<html><head>'
        '<meta property="og:title" content="GitHub Projects Community (@GithubProjects) on X"/>'
        '<title>GitHub Projects Community on X: "CodeNomad wraps OpenCode" / X</title>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    def boom(*_a, **_k):
        raise AssertionError('oEmbed must not run when title tag has post text')

    monkeypatch.setattr(cli.requests, 'get', boom)
    assert cli.get_title_from_url(
        'https://x.com/GithubProjects/status/2075527965958713554'
    ) == 'GitHub Projects Community on X: "CodeNomad wraps OpenCode"'


def test_reddit_og_title(monkeypatch):
    html = (
        '<html><head><meta property="og:title" content="Real Reddit post"/>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    def boom(*_a, **_k):
        raise AssertionError('oEmbed must not run when HTML meta succeeds')

    monkeypatch.setattr(cli.requests, 'get', boom)
    assert cli.get_title_from_url(
        'https://www.reddit.com/r/codex/comments/1usossd/example/'
    ) == 'Real Reddit post'


def test_reddit_verification_title_falls_through_to_oembed(monkeypatch):
    html = '<html><head><title>Reddit - Please wait for verification</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'New GPT-5.6 Sol reverse engineered its own app'}

    def fake_get(url, params=None, **_kwargs):
        assert 'reddit.com/oembed' in url
        assert params.get('url', '').startswith('https://www.reddit.com/')
        return Resp()

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url(
        'https://www.reddit.com/r/codex/comments/1usossd/new_gpt_56_sol_reverse_engineered_its_own_app_in'
    ) == 'New GPT-5.6 Sol reverse engineered its own app'


def test_reddit_verification_placeholder_og_falls_through_to_oembed(monkeypatch):
    html = (
        '<html><head>'
        '<meta property="og:title" content="Reddit - Please wait for verification"/>'
        '<title>Reddit - Please wait for verification</title>'
        '</head><body></body></html>'
    )
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'From oEmbed'}

    monkeypatch.setattr(cli.requests, 'get', lambda *_a, **_k: Resp())
    assert cli.get_title_from_url(
        'https://old.reddit.com/r/test/comments/abc123/slug/'
    ) == 'From oEmbed'


def test_reddit_oembed_empty_title_uses_card_link(monkeypatch):
    html = '<html><head><title>Reddit - Please wait for verification</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {
                'title': '',
                'html': (
                    '<blockquote class="reddit-card">'
                    '<a href="https://www.reddit.com/r/test/comments/1/">Title from card</a> from '
                    '<a href="https://www.reddit.com/r/test/">test</a>'
                    '</blockquote>'
                ),
            }

    monkeypatch.setattr(cli.requests, 'get', lambda *_a, **_k: Resp())
    assert cli.get_title_from_url(
        'https://www.reddit.com/r/test/comments/1/slug/'
    ) == 'Title from card'


def test_reddit_oembed_failure_returns_no_title(monkeypatch):
    html = '<html><head><title>Reddit - Please wait for verification</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)

    def fake_get(*_a, **_k):
        raise requests.ConnectionError('no network')

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    assert cli.get_title_from_url(
        'https://www.reddit.com/r/test/comments/1/slug/'
    ) == 'No title found'


def test_redd_it_short_url_uses_oembed(monkeypatch):
    html = '<html><head><title>Reddit - Please wait for verification</title></head><body></body></html>'
    _patch_subprocess(monkeypatch, html)
    seen = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {'title': 'Short link title'}

    def fake_get(url, params=None, **_kwargs):
        seen['post_url'] = params.get('url')
        return Resp()

    monkeypatch.setattr(cli.requests, 'get', fake_get)
    short = 'https://redd.it/1usossd'
    assert cli.get_title_from_url(short) == 'Short link title'
    assert seen['post_url'] == short
