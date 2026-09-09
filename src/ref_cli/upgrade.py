"""Detect how ref-cli was installed and print upgrade instructions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ref_cli import __version__
from ref_cli.utils.colors import error, highlight, info, warning


def pipx_metadata_path(prefix: Optional[str] = None) -> Path:
    """Return the expected pipx_metadata.json path for this interpreter."""
    root = Path(prefix if prefix is not None else sys.prefix)
    return root / "pipx_metadata.json"


def load_pipx_metadata(path: Path) -> Dict[str, Any]:
    """Load and return pipx metadata JSON."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("pipx metadata root must be an object")
    return data


def _fastapi_importable() -> bool:
    try:
        import fastapi  # noqa: F401
    except ImportError:
        return False
    return True


def has_api_extra(metadata: Dict[str, Any]) -> bool:
    """True when ref-cli[api] was injected or FastAPI is importable."""
    injected = metadata.get("injected_packages") or {}
    if isinstance(injected, dict):
        for payload in injected.values():
            if not isinstance(payload, dict):
                continue
            package_or_url = str(payload.get("package_or_url") or "")
            if "[api]" in package_or_url:
                return True
    return _fastapi_importable()


def classify_upgrade_command(package_or_url: str) -> str:
    """Return the primary shell command to upgrade from ``package_or_url``."""
    source = (package_or_url or "").strip()
    if not source:
        raise ValueError("Missing package_or_url in pipx metadata")

    if source.startswith("git+"):
        return f"pipx install --force '{source}'"

    path = Path(source)
    if path.is_absolute() or source.startswith(".") or path.exists():
        return f"pipx install --force {source}"

    # PyPI-style: ref-cli, ref-cli==1.2.3, ref-cli[api]
    return "pipx upgrade ref-cli"


def build_upgrade_steps(
    metadata: Dict[str, Any],
    *,
    systemd_unit: Optional[Path] = None,
) -> Tuple[str, str, List[str]]:
    """
    Return ``(source, installed_version, commands)`` from pipx metadata.

    ``commands`` is an ordered list of shell commands to run.
    """
    main = metadata.get("main_package") or {}
    if not isinstance(main, dict):
        raise ValueError("pipx metadata main_package must be an object")

    source = str(main.get("package_or_url") or "").strip()
    installed_version = str(main.get("package_version") or "unknown").strip()
    commands = [classify_upgrade_command(source)]

    if has_api_extra(metadata):
        commands.append("pipx inject ref-cli 'ref-cli[api]'")

    unit = systemd_unit
    if unit is None:
        from ref_cli.server_install import SYSTEMD_UNIT

        unit = SYSTEMD_UNIT
    if unit.exists():
        commands.append("systemctl --user restart ref-api")

    return source, installed_version, commands


def report_upgrade_instructions(
    *,
    prefix: Optional[str] = None,
    systemd_unit: Optional[Path] = None,
) -> int:
    """Print how to upgrade this install; return a process exit code."""
    print(info(f"ref-cli version: {highlight(__version__)}"))

    meta_path = pipx_metadata_path(prefix)
    if not meta_path.is_file():
        print(warning("Install source: not detected as a pipx venv."))
        print(
            info(
                "Reinstall with your original method (pipx / pip / editable). "
                "Example: pipx install --force /path/to/ref  or  pipx upgrade ref-cli"
            )
        )
        return 0

    try:
        metadata = load_pipx_metadata(meta_path)
        source, installed_version, commands = build_upgrade_steps(
            metadata,
            systemd_unit=systemd_unit,
        )
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        print(error(f"Could not read pipx metadata at {meta_path}: {exc}"))
        return 1

    print(info(f"pipx package version: {highlight(installed_version)}"))
    print(info(f"Install source: {highlight(source)}"))
    print(info("To upgrade, run:"))
    for command in commands:
        print(command)
    return 0
