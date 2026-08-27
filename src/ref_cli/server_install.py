"""Install and manage a user-level systemd service for ref-api."""

from __future__ import annotations

import importlib.resources
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from ref_cli.utils.colors import error, info, success, warning

CONFIG_DIR = Path.home() / ".config" / "ref"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
REF_API_ENV = CONFIG_DIR / "ref-api.env"
REF_API_ENV_TEMPLATE = CONFIG_DIR / "ref-api.env.template"
SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"
SYSTEMD_UNIT = SYSTEMD_USER_DIR / "ref-api.service"
SERVICE_NAME = "ref-api.service"


def _template_text(name: str) -> str:
    with importlib.resources.files("ref_cli").joinpath(f"config/{name}").open(
        "r", encoding="utf-8"
    ) as handle:
        return handle.read()


def bootstrap_config_dir(*, created: Optional[list[str]] = None) -> Path:
    """
    Ensure ~/.config/ref exists with a documented config.yaml template.

    Returns the config directory path.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(_template_text("config.yaml.template"), encoding="utf-8")
        if created is not None:
            created.append(str(CONFIG_FILE))
    else:
        _merge_missing_config_keys()

    if not REF_API_ENV.exists() and not REF_API_ENV_TEMPLATE.exists():
        REF_API_ENV_TEMPLATE.write_text(
            _template_text("ref-api.env.template"), encoding="utf-8"
        )
        if created is not None:
            created.append(str(REF_API_ENV_TEMPLATE))

    return CONFIG_DIR


def _merge_missing_config_keys() -> None:
    """Add keys from default_config.yaml that are missing in user config."""
    import yaml

    from ref_cli.cli import get_default_config

    with CONFIG_FILE.open("r", encoding="utf-8") as handle:
        user_config = yaml.safe_load(handle) or {}

    default_config = get_default_config()
    updated = False
    for key, value in default_config.items():
        if key not in user_config:
            user_config[key] = value
            updated = True

    if updated:
        with CONFIG_FILE.open("w", encoding="utf-8") as handle:
            yaml.dump(user_config, handle)


def bootstrap_archive_paths() -> None:
    """Ensure ~/references layout exists (same as ref main)."""
    from ref_cli.cli import UNIFIED, TRANSCRIPT_PENDING_FILE, ensure_path_exists

    ensure_path_exists(UNIFIED)
    ensure_path_exists(TRANSCRIPT_PENDING_FILE)


def _api_deps_available() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_api_dependencies() -> None:
    """Ensure FastAPI/uvicorn are importable; pipx inject when possible."""
    if _api_deps_available():
        return

    pipx = shutil.which("pipx")
    if not pipx:
        raise RuntimeError(
            "ref-api dependencies are not installed.\n"
            "Install with: pip install 'ref-cli[api]'\n"
            "Or with pipx: pipx inject ref-cli 'ref-cli[api]'"
        )

    print(info("Installing ref-api dependencies via pipx inject…"))
    subprocess.run(
        [pipx, "inject", "ref-cli", "ref-cli[api]"],
        check=True,
    )
    if not _api_deps_available():
        raise RuntimeError("pipx inject completed but ref-api dependencies are still missing.")


def resolve_ref_api_binary() -> str:
    path = shutil.which("ref-api")
    if not path:
        raise RuntimeError(
            "ref-api executable not found on PATH after installing dependencies."
        )
    return path


def set_local_api_url(host: str, port: int) -> bool:
    """
    Point api_url at this machine's ref-api when still unset.

    Returns True if the config file was modified.
    """
    if not CONFIG_FILE.exists():
        return False

    import yaml

    with CONFIG_FILE.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    current = config.get("api_url")
    if current not in (None, "", "null", "None"):
        return False

    if host in ("0.0.0.0", "::"):
        url = f"http://127.0.0.1:{port}"
    else:
        url = f"http://{host}:{port}"

    text = CONFIG_FILE.read_text(encoding="utf-8")
    if re.search(r"^api_url:\s*null\s*$", text, flags=re.MULTILINE):
        text = re.sub(
            r"^api_url:\s*null\s*$",
            f"api_url: {url}",
            text,
            count=1,
            flags=re.MULTILINE,
        )
        CONFIG_FILE.write_text(text, encoding="utf-8")
        return True

    config["api_url"] = url
    with CONFIG_FILE.open("w", encoding="utf-8") as handle:
        yaml.dump(config, handle)
    return True


def _systemd_unit_body(ref_api_bin: str, host: str, port: int, env_file: Path) -> str:
    return f"""[Unit]
Description=ref URL archive API (ref-api)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={ref_api_bin} --host {host} --port {port}
EnvironmentFile=-{env_file}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def write_systemd_unit(ref_api_bin: str, host: str, port: int) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    REF_API_ENV.touch(exist_ok=True)
    SYSTEMD_UNIT.write_text(
        _systemd_unit_body(ref_api_bin, host, port, REF_API_ENV),
        encoding="utf-8",
    )
    return SYSTEMD_UNIT


def _run_systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
    )


def _systemd_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    result = _run_systemctl("status")
    # status may fail if no user session units, but systemctl exists
    return result.returncode in (0, 1, 3, 4)


def install_server(*, host: str = "0.0.0.0", port: int = 8000) -> int:
    """Bootstrap config, install API deps, write user systemd unit, enable service."""
    created: list[str] = []
    try:
        bootstrap_config_dir(created=created)
        bootstrap_archive_paths()
        ensure_api_dependencies()
        ref_api_bin = resolve_ref_api_binary()

        if not _systemd_available():
            print(
                error(
                    "systemd user session not available. "
                    f"Run manually: {ref_api_bin} --host {host} --port {port}"
                )
            )
            return 1

        unit_path = write_systemd_unit(ref_api_bin, host, port)
        if set_local_api_url(host, port):
            print(info(f"Set api_url to local ref-api in {CONFIG_FILE}"))

        reload = _run_systemctl("daemon-reload")
        if reload.returncode != 0:
            print(error(reload.stderr.strip() or "systemctl daemon-reload failed"))
            return 1

        enable = _run_systemctl("enable", "--now", SERVICE_NAME)
        if enable.returncode != 0:
            print(error(enable.stderr.strip() or f"Failed to enable {SERVICE_NAME}"))
            return 1

        for path in created:
            print(info(f"Created {path}"))

        print(success(f"Installed {unit_path}"))
        print(success(f"Started {SERVICE_NAME} on {host}:{port}"))
        print(info(f"Environment file: {REF_API_ENV} (optional keys)"))
        print(
            info(
                "For ref-api at boot without login: loginctl enable-linger $USER"
            )
        )
        print(info(f"Check status: ref --server-status"))
        return 0
    except subprocess.CalledProcessError as exc:
        print(error(f"Command failed: {exc}"))
        return 1
    except RuntimeError as exc:
        print(error(str(exc)))
        return 1


def uninstall_server() -> int:
    """Disable and remove the user systemd unit."""
    if not SYSTEMD_UNIT.exists():
        print(warning(f"No unit file at {SYSTEMD_UNIT}"))
        return 0

    if _systemd_available():
        _run_systemctl("disable", "--now", SERVICE_NAME)
        _run_systemctl("daemon-reload")

    SYSTEMD_UNIT.unlink(missing_ok=True)
    print(success(f"Removed {SERVICE_NAME}"))
    return 0


def server_status() -> int:
    """Print systemd status for ref-api."""
    if not _systemd_available():
        print(error("systemctl --user is not available"))
        return 1

    if not SYSTEMD_UNIT.exists():
        print(warning(f"{SERVICE_NAME} is not installed ({SYSTEMD_UNIT} missing)"))
        return 1

    result = subprocess.run(
        ["systemctl", "--user", "status", SERVICE_NAME],
    )
    return 0 if result.returncode in (0, 3) else result.returncode
