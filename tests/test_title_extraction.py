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
