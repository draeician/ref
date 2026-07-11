"""Tests for references.md title repair helpers and CLIs."""

from ref_cli import fix_reddit_titles, fix_x_titles, title_fixer
from ref_cli.cli import _is_reddit_url, _is_x_or_twitter_url


SAMPLE_LINES = """Date|URL|Title|Source|TypG
2024-01-01T00:00:00|[https://x.com/user/status/1]|(old x title)|General|General
2024-01-01T00:00:01|[https://example.com/page]|(leave me alone)|General|General
2024-01-01T00:00:02|[https://www.reddit.com/r/test/comments/abc/slug/]|(Reddit - Dive into anything)|General|General
2024-01-01T00:00:03|[https://twitter.com/user/status/2]|(No title found)|General|General
2024-01-01T00:00:04|[_https://redd.it/xyz]|()|General|General
"""


def test_extract_url_and_title():
    assert title_fixer.extract_url('[https://x.com/a]') == 'https://x.com/a'
    assert title_fixer.extract_url('[_https://redd.it/x]') == 'https://redd.it/x'
    assert title_fixer.extract_title('(Hello world)') == 'Hello world'
    assert title_fixer.extract_title('()') == ''


def test_replace_title_preserves_other_fields():
    line = '2024-01-01T00:00:00|[https://x.com/a]|(old)|Uploader|YouTube|transcript.json\n'
    updated = title_fixer.replace_title(line, 'new title')
    assert updated == (
        '2024-01-01T00:00:00|[https://x.com/a]|(new title)|Uploader|YouTube|transcript.json\n'
    )


def test_is_usable_title():
    assert title_fixer.is_usable_title('Real title')
    assert not title_fixer.is_usable_title('No title found')
    assert not title_fixer.is_usable_title('Error: Request timed out')
    assert not title_fixer.is_usable_title('')
    assert not title_fixer.is_usable_title(None)


def test_repair_titles_dry_run_does_not_write(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')

    def fake_fetch(url):
        if 'x.com' in url or 'twitter.com' in url:
            return f'fresh for {url}'
        raise AssertionError('unexpected url')

    stats = title_fixer.repair_titles(
        str(path),
        _is_x_or_twitter_url,
        apply=False,
        fetch_title=fake_fetch,
    )
    assert stats.matched == 2
    assert stats.would_update == 2
    assert stats.updated == 0
    assert path.read_text(encoding='utf-8') == SAMPLE_LINES


def test_repair_titles_apply_updates_only_matching_titles(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')

    def fake_fetch(url):
        mapping = {
            'https://x.com/user/status/1': 'fresh x one',
            'https://twitter.com/user/status/2': 'fresh twitter two',
        }
        return mapping[url]

    stats = title_fixer.repair_titles(
        str(path),
        _is_x_or_twitter_url,
        apply=True,
        fetch_title=fake_fetch,
    )
    assert stats.matched == 2
    assert stats.updated == 2
    text = path.read_text(encoding='utf-8')
    assert '|(fresh x one)|' in text
    assert '|(fresh twitter two)|' in text
    assert '|(leave me alone)|' in text
    assert '|(Reddit - Dive into anything)|' in text
    # Line order preserved: example.com still second data row
    lines = text.splitlines()
    assert 'example.com' in lines[2]


def test_repair_titles_skips_unusable_fetch(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')

    stats = title_fixer.repair_titles(
        str(path),
        _is_x_or_twitter_url,
        apply=True,
        fetch_title=lambda _url: 'No title found',
    )
    assert stats.failed == 2
    assert stats.updated == 0
    assert path.read_text(encoding='utf-8') == SAMPLE_LINES


def test_repair_titles_ok_when_titles_match(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(
        '2024-01-01T00:00:00|[https://x.com/user/status/1]|(same title)|General|General\n',
        encoding='utf-8',
    )
    stats = title_fixer.repair_titles(
        str(path),
        _is_x_or_twitter_url,
        apply=True,
        fetch_title=lambda _url: 'same title',
    )
    assert stats.ok == 1
    assert stats.updated == 0


def test_repair_titles_limit(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return f'new {url}'

    stats = title_fixer.repair_titles(
        str(path),
        _is_x_or_twitter_url,
        apply=False,
        limit=1,
        fetch_title=fake_fetch,
    )
    assert stats.matched == 1
    assert len(calls) == 1


def test_repair_reddit_titles_apply(tmp_path):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')

    def fake_fetch(url):
        return {
            'https://www.reddit.com/r/test/comments/abc/slug/': 'Real Reddit title',
            'https://redd.it/xyz': 'Short link title',
        }[url]

    stats = title_fixer.repair_titles(
        str(path),
        _is_reddit_url,
        apply=True,
        fetch_title=fake_fetch,
    )
    assert stats.matched == 2
    assert stats.updated == 2
    text = path.read_text(encoding='utf-8')
    assert '|(Real Reddit title)|' in text
    assert '|(Short link title)|' in text
    assert '[_https://redd.it/xyz]' in text  # URL field unchanged


def test_fix_x_titles_cli_dry_run(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')
    monkeypatch.setattr(
        'ref_cli.title_fixer.get_title_from_url',
        lambda url: 'fresh x',
    )
    code = fix_x_titles.main(['--file', str(path)])
    assert code == 0
    assert path.read_text(encoding='utf-8') == SAMPLE_LINES
    out = capsys.readouterr().out
    assert 'DRY-RUN' in out


def test_fix_reddit_titles_cli_apply(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'references.md'
    path.write_text(SAMPLE_LINES, encoding='utf-8')
    monkeypatch.setattr(
        'ref_cli.title_fixer.get_title_from_url',
        lambda url: 'fixed reddit',
    )
    code = fix_reddit_titles.main(['--file', str(path), '--apply'])
    assert code == 0
    text = path.read_text(encoding='utf-8')
    assert text.count('|(fixed reddit)|') == 2
    out = capsys.readouterr().out
    assert 'APPLY' in out
