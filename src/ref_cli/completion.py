"""Shell tab-completion helpers via argcomplete (matching ol/od)."""

from __future__ import annotations

import argparse
from typing import Any, Optional

import argcomplete
from argcomplete.completers import FilesCompleter


def files_completer(allowednames: Optional[tuple] = None) -> Any:
    """Return a FilesCompleter, optionally limited to extensions."""
    if allowednames is None:
        return FilesCompleter()
    return FilesCompleter(allowednames=list(allowednames))


def enable_argcomplete(parser: argparse.ArgumentParser) -> None:
    """Wire argcomplete on ``parser``.

    No-op for normal runs; when the shell sets ``_ARGCOMPLETE``, this exits
    after printing completions (see ``register-python-argcomplete``).
    """
    argcomplete.autocomplete(parser)
