"""Smoke tests for argcomplete wiring on ref CLIs."""

from __future__ import annotations

import argparse

from ref_cli.advisors import build_arg_parser as build_advisors_parser
from ref_cli.completion import enable_argcomplete, files_completer
from ref_cli.title_fixer import build_arg_parser as build_repair_parser


def test_files_completer_attaches() -> None:
    completer = files_completer()
    assert completer is not None


def test_advisors_parser_has_file_completers() -> None:
    parser = build_advisors_parser()
    actions = {a.dest: a for a in parser._actions}
    assert hasattr(actions['file'], 'completer')
    assert hasattr(actions['output'], 'completer')
    # Does not exit when _ARGCOMPLETE is unset
    enable_argcomplete(parser)
    args = parser.parse_args(['--platform', 'web', '--min-count', '3'])
    assert args.platform == 'web'
    assert args.min_count == 3


def test_repair_parser_has_file_completer() -> None:
    parser = build_repair_parser('test repair')
    actions = {a.dest: a for a in parser._actions}
    assert hasattr(actions['file'], 'completer')
    enable_argcomplete(parser)
    args = parser.parse_args(['--limit', '5'])
    assert args.limit == 5


def test_enable_argcomplete_is_noop_without_env(
    monkeypatch,
) -> None:
    monkeypatch.delenv('_ARGCOMPLETE', raising=False)
    parser = argparse.ArgumentParser()
    parser.add_argument('--foo', choices=('a', 'b'))
    enable_argcomplete(parser)
    assert parser.parse_args(['--foo', 'a']).foo == 'a'
