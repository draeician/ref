"""CLI: repair X/Twitter titles in references.md in place."""

from __future__ import annotations

from typing import Optional, Sequence

from ref_cli.cli import _is_x_or_twitter_url
from ref_cli.title_fixer import run_repair_cli


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run_repair_cli(
        'Repair X/Twitter titles in references.md',
        _is_x_or_twitter_url,
        argv,
    )


if __name__ == '__main__':
    raise SystemExit(main())
