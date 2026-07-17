"""Shared file backup helpers (gzip by default)."""

from __future__ import annotations

import gzip
import os
import shutil
from datetime import datetime
from typing import Optional


def backup_file(
    file_path: str,
    *,
    compress: bool = True,
    style: str = 'timestamp_prefix',
) -> str:
    """Copy ``file_path`` to a timestamped backup; gzip by default.

    Args:
        file_path: Source file to back up.
        compress: If True (default), write ``.gz`` with gzip. If False, plain copy.
        style:
            - ``timestamp_prefix`` → ``{dir}/{YYYYMMDDTHHMMSS}_{basename}[.gz]``
              (used by ``ref --backup``).
            - ``suffix`` → ``{path}.bak-{YYYYMMDDTHHMMSS}[.gz]``
              (used by format migrations).

    Returns:
        Path to the backup file created.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        OSError: On I/O failure.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(file_path)

    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    if style == 'suffix':
        dest = f'{file_path}.bak-{stamp}'
    else:
        directory = os.path.dirname(file_path) or '.'
        base = os.path.basename(file_path)
        dest = os.path.join(directory, f'{stamp}_{base}')

    if compress:
        dest = f'{dest}.gz'
        with open(file_path, 'rb') as src, gzip.open(dest, 'wb') as out:
            shutil.copyfileobj(src, out)
    else:
        shutil.copy2(file_path, dest)

    return dest
