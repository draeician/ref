"""Read-only detection of ref installations and upgrade instructions.

``ref --upgrade`` never installs, upgrades, restarts, or changes anything.  It
inspects the running CLI environment, separate pipx metadata, the ref-api
systemd user unit, and GitHub to print host-specific advice only.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from ref_cli import __version__
from ref_cli.utils.colors import dim, highlight, info, success, title, warning

DEFAULT_REPOSITORY = "draeician/ref"
GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 5.0
MIN_ABBREVIATED_SHA = 7

_SHA_RE = re.compile(r"(?:^|[.+-])g([0-9a-f]{7,40})(?:$|[.+-])", re.IGNORECASE)
_REF_NAME_RE = re.compile(r"^ref[-_]cli$", re.IGNORECASE)


@dataclass
class GitHubState:
    repository: str = DEFAULT_REPOSITORY
    default_branch: Optional[str] = None
    latest_sha: Optional[str] = None
    error: Optional[str] = None


@dataclass
class DistributionInfo:
    version: Optional[str] = None
    direct_url: Dict[str, Any] = field(default_factory=dict)
    installer: Optional[str] = None
    dist_info: Optional[Path] = None
    package_dir: Optional[Path] = None


@dataclass
class Installation:
    role: str
    environment: Optional[Path] = None
    executable: Optional[Path] = None
    resolved_executable: Optional[Path] = None
    interpreter: Optional[Path] = None
    version: Optional[str] = None
    revision: Optional[str] = None
    source: Optional[str] = None
    source_kind: str = "unknown"
    editable: bool = False
    pipx_managed: bool = False
    has_api_extra: bool = False
    notes: List[str] = field(default_factory=list)
    status: str = "unknown"
    status_detail: str = ""


@dataclass
class ServiceInfo:
    path: Path
    exists: bool = False
    exec_start: List[str] = field(default_factory=list)
    executable: Optional[Path] = None
    environment: Optional[Path] = None
    host: Optional[str] = None
    port: Optional[int] = None
    error: Optional[str] = None

    @property
    def health_url(self) -> Optional[str]:
        if not self.exists or self.port is None:
            return None
        host = self.host or "127.0.0.1"
        if host in ("0.0.0.0", "::", "[::]"):
            host = "127.0.0.1"
        return f"http://{host}:{self.port}/health"


@dataclass
class UpgradeAction:
    title: str
    install: Installation
    commands: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    restart_service: bool = False


class GitHubError(RuntimeError):
    """A user-facing GitHub lookup failure."""


# ---------------------------------------------------------------------------
# Small file/metadata helpers
# ---------------------------------------------------------------------------


def pipx_metadata_path(prefix: Optional[str] = None) -> Path:
    """Return the conventional pipx metadata path for a venv."""
    root = Path(prefix if prefix is not None else sys.prefix)
    return root / "pipx_metadata.json"


def load_pipx_metadata(path: Path) -> Dict[str, Any]:
    """Load and validate a pipx_metadata.json document."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("pipx metadata root must be an object")
    return data


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _same_path(left: Optional[Path], right: Optional[Path]) -> bool:
    if left is None or right is None:
        return False
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _normalize_dist_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _venv_for_executable(path: Optional[Path]) -> Optional[Path]:
    """Find the nearest venv root containing ``path`` (following symlinks)."""
    if path is None:
        return None
    try:
        candidate = Path(path).expanduser()
        if candidate.exists():
            candidate = candidate.resolve()
    except OSError:
        candidate = Path(path).expanduser()

    for parent in [candidate, *candidate.parents]:
        if (parent / "pyvenv.cfg").is_file():
            return parent

    if candidate.parent.name in ("bin", "Scripts"):
        root = candidate.parent.parent
        if (root / "lib").is_dir() or (root / "Lib").is_dir():
            return root
    return None


def _site_packages(environment: Path) -> List[Path]:
    env = Path(environment)
    patterns = (
        "lib/python*/site-packages",
        "lib64/python*/site-packages",
        "Lib/site-packages",
        "site-packages",
    )
    found: List[Path] = []
    for pattern in patterns:
        found.extend(path for path in env.glob(pattern) if path.is_dir())
    if env.name == "site-packages" and env.is_dir():
        found.append(env)
    unique: List[Path] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def _parse_metadata_version(metadata_file: Path) -> Tuple[Optional[str], Optional[str]]:
    text = _read_text(metadata_file)
    if not text:
        return None, None
    name = None
    version = None
    for line in text.splitlines():
        if not line.strip():
            break
        if line.lower().startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.lower().startswith("version:"):
            version = line.split(":", 1)[1].strip()
    return name, version


def _find_distribution(environment: Optional[Path]) -> DistributionInfo:
    if environment is None:
        return DistributionInfo()
    for site_dir in _site_packages(environment):
        candidates = sorted(site_dir.glob("ref_cli-*.dist-info"))
        candidates += sorted(site_dir.glob("ref-cli-*.dist-info"))
        for dist_info in candidates:
            metadata_file = dist_info / "METADATA"
            name, version = _parse_metadata_version(metadata_file)
            if name is not None and _normalize_dist_name(name) != "ref-cli":
                continue
            direct_url: Dict[str, Any] = {}
            direct_url_file = dist_info / "direct_url.json"
            if direct_url_file.is_file():
                try:
                    loaded = _read_json(direct_url_file)
                    if isinstance(loaded, dict):
                        direct_url = loaded
                except (OSError, ValueError, TypeError):
                    direct_url = {}
            installer = _read_text(dist_info / "INSTALLER")
            return DistributionInfo(
                version=version,
                direct_url=direct_url,
                installer=installer.strip() if installer else None,
                dist_info=dist_info,
                package_dir=site_dir / "ref_cli",
            )

        for egg_info in sorted(site_dir.glob("ref_cli*.egg-info")):
            _, version = _parse_metadata_version(egg_info / "PKG-INFO")
            if version is not None:
                return DistributionInfo(
                    version=version,
                    package_dir=site_dir / "ref_cli",
                    dist_info=egg_info,
                )
    return DistributionInfo()


def _running_distribution() -> DistributionInfo:
    """Fallback for the running interpreter using importlib.metadata."""
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:  # pragma: no cover - Python < 3.8
        return DistributionInfo()
    try:
        dist = importlib_metadata.distribution("ref-cli")
    except importlib_metadata.PackageNotFoundError:
        return DistributionInfo()

    direct_url: Dict[str, Any] = {}
    try:
        raw = dist.read_text("direct_url.json")
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                direct_url = loaded
    except (OSError, ValueError, TypeError):
        direct_url = {}
    return DistributionInfo(
        version=dist.version,
        direct_url=direct_url,
        installer=dist.read_text("INSTALLER"),
    )


def _revision_from_version(version: Optional[str]) -> Optional[str]:
    if not version:
        return None
    match = _SHA_RE.search(version)
    return match.group(1).lower() if match else None


def _revision_from_commit_id(commit_id: Optional[str]) -> Optional[str]:
    if not commit_id:
        return None
    cleaned = str(commit_id).strip().lower()
    if cleaned.startswith("g"):
        cleaned = cleaned[1:]
    if re.fullmatch(r"[0-9a-f]{7,40}", cleaned):
        return cleaned
    return None


def _revision_from_package(environment: Optional[Path]) -> Optional[str]:
    if environment is None:
        return None
    for site_dir in _site_packages(environment):
        version_file = site_dir / "ref_cli" / "_version.py"
        text = _read_text(version_file)
        if not text:
            continue
        match = re.search(
            r"commit_id\s*=\s*['\"]g?([0-9a-f]{7,40})['\"]", text
        )
        if match:
            return match.group(1).lower()
    return None


def _file_url_to_path(value: str) -> Optional[Path]:
    try:
        parsed = urlparse.urlparse(value)
    except ValueError:
        return None
    if parsed.scheme != "file":
        return None
    path = urlparse.unquote(parsed.path)
    if parsed.netloc and parsed.netloc not in ("", "localhost"):
        path = f"//{parsed.netloc}{path}"
    return Path(path)


def _strip_extras(source: str) -> str:
    return re.sub(r"\[[^\]]*\]$", "", source.strip())


def _looks_like_path(source: str) -> bool:
    stripped = _strip_extras(source)
    return (
        stripped.startswith(("/", "./", "../", "~", "file://"))
        or Path(stripped).is_absolute()
        or Path(stripped).exists()
    )


def _looks_like_artifact(source: str) -> bool:
    path = Path(_strip_extras(source))
    return path.suffix.lower() in (".whl", ".zip", ".gz", ".tar") or (
        path.is_file()
    )


def _source_from_pipx(metadata: Dict[str, Any]) -> Tuple[Optional[str], str]:
    main = metadata.get("main_package") or {}
    if not isinstance(main, dict):
        return None, "unknown"
    source = str(main.get("package_or_url") or "").strip()
    if not source:
        return None, "unknown"
    if source.startswith("git+"):
        return source, "pipx-git"
    if _looks_like_path(source):
        return source, "pipx-local"
    return source, "pipx-pypi"


def _source_from_direct_url(
    direct_url: Dict[str, Any],
) -> Tuple[Optional[str], str, bool]:
    if not direct_url:
        return None, "unknown", False
    vcs_info = direct_url.get("vcs_info")
    if isinstance(vcs_info, dict) and vcs_info:
        url = str(direct_url.get("url") or "").strip() or None
        if url and not url.startswith("git+"):
            url = f"git+{url}"
        return url, "git", False
    dir_info = direct_url.get("dir_info")
    if isinstance(dir_info, dict):
        url = str(direct_url.get("url") or "").strip()
        path = _file_url_to_path(url)
        source = str(path) if path is not None else (url or None)
        editable = bool(dir_info.get("editable"))
        if editable:
            return source, "editable", True
        if source is not None and _looks_like_artifact(source):
            return source, "artifact", False
        return source, "local", False
    url = str(direct_url.get("url") or "").strip()
    if url:
        path = _file_url_to_path(url)
        if path is not None:
            kind = "artifact" if _looks_like_artifact(str(path)) else "local"
            return str(path), kind, False
        return url, "unknown", False
    return None, "unknown", False


def _has_api_packages(environment: Optional[Path]) -> bool:
    if environment is None:
        return False
    for site_dir in _site_packages(environment):
        if list(site_dir.glob("fastapi-*.dist-info")) and list(
            site_dir.glob("uvicorn-*.dist-info")
        ):
            return True
    return False


def _pipx_api_injected(metadata: Optional[Dict[str, Any]]) -> bool:
    if not metadata:
        return False
    injected = metadata.get("injected_packages") or {}
    if not isinstance(injected, dict):
        return False
    for payload in injected.values():
        if not isinstance(payload, dict):
            continue
        package_or_url = str(payload.get("package_or_url") or "")
        if "[api]" in package_or_url:
            return True
    return False


# ---------------------------------------------------------------------------
# Installation detection
# ---------------------------------------------------------------------------


def _load_pipx_for_environment(
    environment: Optional[Path],
) -> Tuple[Optional[Dict[str, Any]], Optional[Path], List[str]]:
    if environment is None:
        return None, None, []
    path = environment / "pipx_metadata.json"
    if not path.is_file():
        return None, None, []
    try:
        return load_pipx_metadata(path), path, []
    except (OSError, ValueError, TypeError) as exc:
        return None, path, [f"Could not read pipx metadata at {path}: {exc}"]


def detect_installation(
    role: str,
    environment: Optional[Path],
    *,
    executable: Optional[Path] = None,
    resolved_executable: Optional[Path] = None,
    pipx_metadata: Optional[Dict[str, Any]] = None,
    pipx_metadata_file: Optional[Path] = None,
) -> Installation:
    """Inspect one Python environment read-only."""
    environment = Path(environment) if environment is not None else None
    notes: List[str] = []
    metadata = pipx_metadata
    metadata_file = pipx_metadata_file
    if metadata is None and environment is not None:
        metadata, metadata_file, metadata_notes = _load_pipx_for_environment(
            environment
        )
        notes.extend(metadata_notes)

    dist = _find_distribution(environment)
    if dist.version is None and _same_path(environment, Path(sys.prefix)):
        running = _running_distribution()
        if running.version is not None:
            dist = running
    if dist.version is None and _same_path(environment, Path(sys.prefix)):
        dist.version = __version__

    pipx_source = None
    pipx_kind = "unknown"
    if metadata is not None:
        pipx_source, pipx_kind = _source_from_pipx(metadata)
    direct_source, direct_kind, editable = _source_from_direct_url(dist.direct_url)

    source = pipx_source or direct_source
    source_kind = pipx_kind if pipx_source else direct_kind

    version = dist.version
    if metadata is not None:
        main = metadata.get("main_package") or {}
        if isinstance(main, dict):
            metadata_version = str(main.get("package_version") or "").strip()
            if metadata_version:
                version = metadata_version

    commit_id = None
    vcs_info = dist.direct_url.get("vcs_info")
    if isinstance(vcs_info, dict):
        commit_id = vcs_info.get("commit_id")
    revision = _revision_from_commit_id(commit_id)
    if revision is None:
        revision = _revision_from_version(version)
    if revision is None:
        revision = _revision_from_package(environment)

    has_api_extra = _pipx_api_injected(metadata) or _has_api_packages(environment)
    interpreter = None
    if environment is not None:
        candidate = environment / "bin" / "python"
        if not candidate.exists():
            candidate = environment / "Scripts" / "python.exe"
        if candidate.exists():
            interpreter = candidate

    if metadata_file is not None and metadata is None:
        notes.append(f"pipx metadata exists at {metadata_file} but is unusable.")
    if environment is not None and dist.version is None:
        notes.append(
            f"No ref-cli package metadata was found in {environment}; "
            "the installed version and revision are unknown."
        )
    if source is None:
        notes.append(
            "Installation source could not be determined from pipx metadata or "
            "PEP 610 direct_url.json."
        )

    return Installation(
        role=role,
        environment=environment,
        executable=Path(executable) if executable else None,
        resolved_executable=(
            Path(resolved_executable) if resolved_executable else None
        ),
        interpreter=interpreter,
        version=version,
        revision=revision,
        source=source,
        source_kind=source_kind,
        editable=editable,
        pipx_managed=metadata is not None,
        has_api_extra=has_api_extra,
        notes=notes,
    )


def _running_cli_executable() -> Optional[Path]:
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0:
        candidate = Path(argv0).expanduser()
        if candidate.name.lower().startswith("ref") and candidate.exists():
            return candidate
    which = shutil.which("ref")
    return Path(which) if which else None


def detect_cli_installation(
    *,
    cli_environment: Optional[Path] = None,
    cli_executable: Optional[Path] = None,
) -> Installation:
    environment = Path(cli_environment) if cli_environment is not None else Path(
        sys.prefix
    )
    executable = cli_executable or _running_cli_executable()
    resolved = None
    if executable is not None:
        try:
            resolved = executable.resolve()
        except OSError:
            resolved = executable
    install = detect_installation(
        "ref-cli",
        environment,
        executable=executable,
        resolved_executable=resolved,
    )
    executable_environment = _venv_for_executable(executable)
    if (
        executable_environment is not None
        and not _same_path(executable_environment, environment)
    ):
        install.notes.append(
            "The ref executable resolves into a different environment "
            f"({executable_environment}) than the running interpreter ({environment})."
        )
    if executable is not None and resolved is not None and (
        Path(executable).is_symlink() or Path(executable).absolute() != resolved
    ):
        install.notes.append(f"Executable symlink resolves to {resolved}.")
    return install


def _parse_exec_start(text: str) -> List[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("execstart="):
            value = stripped.split("=", 1)[1].strip()
            value = value.lstrip("+-@!")
            try:
                return shlex.split(value)
            except ValueError:
                return value.split()
    return []


def detect_service(systemd_unit: Optional[Path] = None) -> ServiceInfo:
    path = Path(systemd_unit) if systemd_unit is not None else Path(
        _default_systemd_unit()
    )
    if not path.is_file():
        return ServiceInfo(path=path, exists=False)
    text = _read_text(path)
    if text is None:
        return ServiceInfo(path=path, exists=True, error=f"Could not read {path}")
    exec_start = _parse_exec_start(text)
    if not exec_start:
        return ServiceInfo(
            path=path,
            exists=True,
            error="No ExecStart line found in the systemd unit",
        )
    executable = Path(exec_start[0]).expanduser()
    environment = _venv_for_executable(executable)
    host = None
    port = None
    for index, token in enumerate(exec_start):
        if token == "--host" and index + 1 < len(exec_start):
            host = exec_start[index + 1]
        elif token.startswith("--host="):
            host = token.split("=", 1)[1]
        elif token == "--port" and index + 1 < len(exec_start):
            try:
                port = int(exec_start[index + 1])
            except ValueError:
                port = None
        elif token.startswith("--port="):
            try:
                port = int(token.split("=", 1)[1])
            except ValueError:
                port = None
    return ServiceInfo(
        path=path,
        exists=True,
        exec_start=exec_start,
        executable=executable,
        environment=environment,
        host=host,
        port=port,
    )


def _default_systemd_unit() -> Path:
    from ref_cli.server_install import SYSTEMD_UNIT

    return Path(SYSTEMD_UNIT)


def detect_api_installation(
    systemd_unit: Optional[Path] = None,
    service: Optional[ServiceInfo] = None,
) -> Tuple[Optional[Installation], ServiceInfo]:
    service = service or detect_service(systemd_unit)
    if not service.exists or service.executable is None:
        return None, service
    install = detect_installation(
        "ref-api",
        service.environment,
        executable=service.executable,
    )
    return install, service


def _pipx_entry_is_ref(package: str, source: str) -> bool:
    if package and _REF_NAME_RE.match(package):
        return True
    if not source:
        return False
    base = _strip_extras(source).strip()
    if base.startswith("git+"):
        base = base[4:]
    name = base.rstrip("/").rsplit("/", 1)[-1].rsplit("@", 1)[0]
    if name.endswith(".git"):
        name = name[:-4]
    return bool(_REF_NAME_RE.match(name)) or name.lower() == "ref"


def _pipx_home_candidates(pipx_home: Optional[Path]) -> List[Path]:
    if pipx_home is not None:
        return [Path(pipx_home).expanduser()]
    candidates: List[Path] = []
    env_home = os.environ.get("PIPX_HOME")
    if env_home:
        candidates.append(Path(env_home).expanduser())
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        candidates.append(Path(xdg_data_home).expanduser() / "pipx")
    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "share" / "pipx",
            home / ".local" / "pipx",
        ]
    )
    unique: List[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def discover_pipx_installations(
    *,
    pipx_home: Optional[Path] = None,
) -> List[Installation]:
    """Find ref-cli installations recorded by pipx, without running pipx."""
    installs: List[Installation] = []
    seen: List[Path] = []
    for home in _pipx_home_candidates(pipx_home):
        venvs_dir = home / "venvs"
        if not venvs_dir.is_dir():
            continue
        for venv in sorted(venvs_dir.iterdir()):
            if not venv.is_dir():
                continue
            metadata_file = venv / "pipx_metadata.json"
            if not metadata_file.is_file():
                continue
            metadata = None
            notes: List[str] = []
            try:
                metadata = load_pipx_metadata(metadata_file)
            except (OSError, ValueError, TypeError) as exc:
                notes.append(f"Could not read pipx metadata at {metadata_file}: {exc}")
            is_ref = bool(_REF_NAME_RE.match(venv.name))
            if metadata is not None:
                main = metadata.get("main_package") or {}
                if isinstance(main, dict):
                    package = str(main.get("package") or "").strip()
                    source = str(main.get("package_or_url") or "").strip()
                    if not _pipx_entry_is_ref(package, source):
                        continue
                    if package or source:
                        is_ref = True
            if not is_ref:
                continue
            if any(_same_path(venv, existing) for existing in seen):
                continue
            seen.append(venv)
            install = detect_installation(
                f"pipx:{venv.name}",
                venv,
                pipx_metadata=metadata,
                pipx_metadata_file=metadata_file,
            )
            install.pipx_managed = True
            install.notes = notes + install.notes
            installs.append(install)
    return installs


# ---------------------------------------------------------------------------
# GitHub lookup
# ---------------------------------------------------------------------------


def _github_get_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
    request = urlrequest.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ref-cli-upgrade-check",
        },
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best-effort error body only
            pass
        lowered = body.lower()
        if exc.code in (403, 429) or "rate limit" in lowered:
            raise GitHubError("GitHub API rate limit exceeded") from exc
        if exc.code == 404:
            raise GitHubError(f"GitHub resource not found (HTTP 404): {url}") from exc
        raise GitHubError(f"GitHub returned HTTP {exc.code}") from exc
    except urlerror.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise GitHubError("GitHub request timed out") from exc
        raise GitHubError(f"GitHub unavailable: {reason}") from exc
    except (TimeoutError, OSError) as exc:
        if "timed out" in str(exc).lower():
            raise GitHubError("GitHub request timed out") from exc
        raise GitHubError(f"GitHub unavailable: {exc}") from exc
    except (UnicodeError, ValueError) as exc:
        raise GitHubError(f"Could not parse the GitHub response: {exc}") from exc
    try:
        return json.loads(payload)
    except (TypeError, ValueError) as exc:
        raise GitHubError(f"Could not parse the GitHub response: {exc}") from exc


def check_github(
    *,
    repository: str = DEFAULT_REPOSITORY,
    timeout: float = DEFAULT_TIMEOUT,
    fetcher: Optional[Callable[[str, float], Any]] = None,
) -> GitHubState:
    """Return the default branch and latest revision for a repository."""
    fetch = fetcher or _github_get_json
    repo_url = f"{GITHUB_API}/repos/{repository}"
    try:
        repo_data = fetch(repo_url, timeout)
    except GitHubError as exc:
        return GitHubState(repository=repository, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - reported, never raised to the user
        return GitHubState(repository=repository, error=f"GitHub unavailable: {exc}")
    if not isinstance(repo_data, dict):
        return GitHubState(
            repository=repository, error="GitHub repository response was not an object"
        )
    branch = str(repo_data.get("default_branch") or "").strip()
    if not branch:
        return GitHubState(
            repository=repository, error="GitHub did not report a default branch"
        )
    commit_url = (
        f"{GITHUB_API}/repos/{repository}/commits/"
        f"{urlparse.quote(branch, safe='')}"
    )
    try:
        commit_data = fetch(commit_url, timeout)
    except GitHubError as exc:
        return GitHubState(
            repository=repository, default_branch=branch, error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001
        return GitHubState(
            repository=repository,
            default_branch=branch,
            error=f"GitHub unavailable: {exc}",
        )
    sha = None
    if isinstance(commit_data, dict):
        sha = str(commit_data.get("sha") or "").strip() or None
    if not sha:
        return GitHubState(
            repository=repository,
            default_branch=branch,
            error="GitHub did not report a commit SHA",
        )
    return GitHubState(
        repository=repository, default_branch=branch, latest_sha=sha.lower()
    )


# ---------------------------------------------------------------------------
# Comparison and status
# ---------------------------------------------------------------------------


def compare_revisions(installed: Optional[str], latest: Optional[str]) -> str:
    """Return ``current``/``outdated``/``unknown`` using prefix matching."""
    if not installed or not latest:
        return "unknown"
    left = str(installed).strip().lower().lstrip("g")
    right = str(latest).strip().lower().lstrip("g")
    if len(left) < MIN_ABBREVIATED_SHA or len(right) < MIN_ABBREVIATED_SHA:
        return "unknown"
    if not re.fullmatch(r"[0-9a-f]+", left) or not re.fullmatch(
        r"[0-9a-f]+", right
    ):
        return "unknown"
    if left.startswith(right) or right.startswith(left):
        return "current"
    return "outdated"


def _short_sha(value: Optional[str], length: int = 12) -> str:
    if not value:
        return "unknown"
    return value[:length]


def evaluate_status(install: Optional[Installation], github: GitHubState) -> None:
    if install is None:
        install_status = ("not-detected", "not installed")
    elif github.error:
        install_status = ("unknown", f"GitHub lookup failed: {github.error}")
    elif not install.version:
        install_status = ("unknown", "installed package version unavailable")
    elif not github.latest_sha:
        install_status = ("unknown", "latest GitHub revision unavailable")
    elif not install.revision:
        install_status = (
            "unknown",
            (
                f"installed version is {install.version}, but no Git revision is "
                "recorded; the GitHub revision cannot be compared"
            ),
        )
    else:
        comparison = compare_revisions(install.revision, github.latest_sha)
        branch = github.default_branch or "the default branch"
        if comparison == "current":
            detail = (
                f"matches GitHub {branch} ({_short_sha(github.latest_sha)})"
            )
            if install.editable:
                detail += "; editable source, uncommitted changes not compared"
            install_status = ("current", detail)
        elif comparison == "outdated":
            install_status = (
                "outdated",
                (
                    f"installed {_short_sha(install.revision)} does not match "
                    f"GitHub {branch} ({_short_sha(github.latest_sha)})"
                ),
            )
        else:
            install_status = (
                "unknown",
                "the installed or GitHub revision is too short or malformed",
            )
    if install is not None:
        install.status, install.status_detail = install_status


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------


def pin_git_source(source: str, revision: Optional[str]) -> str:
    """Pin a ``git+`` source to a revision while preserving its repository."""
    source = source.strip()
    if not revision:
        return source
    if ".git@" in source:
        base = source.split(".git@", 1)[0] + ".git"
    else:
        at_index = source.rfind("@")
        slash_index = source.rfind("/")
        base = source[:at_index] if at_index > slash_index else source
    return f"{base}@{revision}"


def _source_with_extras(source: str, *, api: bool) -> str:
    if not api:
        return _strip_extras(source)
    base = _strip_extras(source)
    return f"{base}[api]"


def _venv_python(install: Installation) -> Optional[str]:
    if install.interpreter is not None:
        return str(install.interpreter)
    if install.environment is not None:
        candidate = install.environment / "bin" / "python"
        if candidate.exists():
            return str(candidate)
        candidate = install.environment / "Scripts" / "python.exe"
        if candidate.exists():
            return str(candidate)
    return None


def _upgrade_commands(
    install: Installation,
    *,
    latest_sha: Optional[str],
    api_required: bool,
    repository: str = DEFAULT_REPOSITORY,
) -> Tuple[List[str], List[str], Optional[str]]:
    """Return commands, notes, and an explanation when no command is possible."""
    source = install.source
    kind = install.source_kind
    notes: List[str] = []
    if not source:
        return (
            [],
            notes,
            (
                "The installation source is unknown, so no safe upgrade command "
                "can be recommended. Inspect the environment's pipx metadata or "
                "PEP 610 direct_url.json to identify how it was installed."
            ),
        )

    if kind.startswith("pipx"):
        if kind == "pipx-git":
            pinned = pin_git_source(source, latest_sha)
            commands = [f"pipx install --force {shlex.quote(pinned)}"]
        elif kind == "pipx-local":
            path = _strip_extras(source)
            commands = [f"pipx install --force {shlex.quote(path)}"]
            if latest_sha:
                notes.append(
                    f"Ensure {path} is checked out at {latest_sha} before reinstalling."
                )
        elif kind == "pipx-pypi":
            commands = ["pipx upgrade ref-cli"]
            notes.append(
                "This installs the latest PyPI release; it does not fetch "
                "unreleased GitHub commits."
            )
        else:
            return ([], notes, "Unknown pipx installation source.")
        if api_required:
            commands.append("pipx inject ref-cli 'ref-cli[api]'")
        return commands, notes, None

    python = _venv_python(install)
    if python is None:
        return (
            [],
            notes,
            "The Python interpreter for this environment could not be found.",
        )
    py = shlex.quote(python)
    if kind == "git":
        pinned = pin_git_source(source, latest_sha)
        spec = f"ref-cli[api] @ {pinned}" if api_required else f"ref-cli @ {pinned}"
        return (
            [f"{py} -m pip install --upgrade {shlex.quote(spec)}"],
            notes,
            None,
        )
    if kind == "editable":
        spec = _source_with_extras(source, api=api_required)
        return (
            [f"{py} -m pip install --upgrade -e {shlex.quote(spec)}"],
            notes,
            None,
        )
    if kind == "local":
        spec = _source_with_extras(source, api=api_required)
        commands = [f"{py} -m pip install --upgrade {shlex.quote(spec)}"]
        if latest_sha:
            notes.append(
                f"Ensure {source} is checked out at {latest_sha} before reinstalling."
            )
        return commands, notes, None
    if kind == "artifact":
        notes.append(
            f"This environment was installed from a local artifact ({source}); "
            "direct_url.json does not record the Git repository it was built from."
        )
        if not latest_sha:
            return (
                [],
                notes,
                (
                    "The local artifact does not record its repository, and the "
                    "latest GitHub revision is unavailable, so no reproducible "
                    "upgrade command can be derived."
                ),
            )
        pinned = f"git+https://github.com/{repository}.git@{latest_sha}"
        spec = f"ref-cli[api] @ {pinned}" if api_required else f"ref-cli @ {pinned}"
        notes.append(
            "If this artifact was built from that repository, reinstall "
            "reproducibly with:"
        )
        return [f"{py} -m pip install --upgrade {shlex.quote(spec)}"], notes, None
    if kind == "pypi":
        spec = "ref-cli[api]" if api_required else "ref-cli"
        return (
            [f"{py} -m pip install --upgrade {shlex.quote(spec)}"],
            notes,
            None,
        )
    return (
        [],
        notes,
        (
            "The installation source type is unknown, so no safe upgrade command "
            "can be recommended."
        ),
    )


def _rollback_command(
    install: Installation, *, api_required: bool
) -> Optional[str]:
    source = install.source
    revision = install.revision
    if not source:
        return None
    if install.source_kind == "pipx-git":
        if not revision:
            return None
        return f"pipx install --force {shlex.quote(pin_git_source(source, revision))}"
    if install.source_kind == "pipx-pypi":
        if not install.version:
            return None
        return f"pipx install --force {shlex.quote(f'ref-cli=={install.version}')}"
    if install.source_kind == "pipx-local":
        return f"pipx install --force {shlex.quote(_strip_extras(source))}"
    if install.source_kind == "git":
        if not revision:
            return None
        python = _venv_python(install)
        if python is None:
            return None
        pinned = pin_git_source(source, revision)
        spec = f"ref-cli[api] @ {pinned}" if api_required else f"ref-cli @ {pinned}"
        return (
            f"{shlex.quote(python)} -m pip install --force-reinstall "
            f"{shlex.quote(spec)}"
        )
    if install.source_kind == "pypi" and install.version:
        python = _venv_python(install)
        if python is None:
            return None
        spec = f"ref-cli[api]=={install.version}" if api_required else (
            f"ref-cli=={install.version}"
        )
        return (
            f"{shlex.quote(python)} -m pip install --force-reinstall "
            f"{shlex.quote(spec)}"
        )
    if install.source_kind in ("local", "editable", "artifact"):
        python = _venv_python(install)
        if python is None:
            return None
        spec = _source_with_extras(source, api=api_required)
        editable_flag = " -e" if install.source_kind == "editable" else ""
        return (
            f"{shlex.quote(python)} -m pip install --force-reinstall"
            f"{editable_flag} {shlex.quote(spec)}"
        )
    return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _installation_label(install: Installation) -> str:
    kind = install.source_kind
    if kind.startswith("pipx"):
        return f"pipx ({kind.split('-', 1)[1]})"
    if kind == "git":
        return "dedicated virtualenv (Git)"
    if kind == "editable":
        return "editable source"
    if kind == "local":
        return "dedicated virtualenv (local source)"
    if kind == "artifact":
        return "dedicated virtualenv (local artifact)"
    if kind == "pypi":
        return "dedicated virtualenv (PyPI)"
    return "unknown"


def _print_installation(
    heading: str,
    install: Installation,
    github: GitHubState,
    *,
    service: Optional[ServiceInfo] = None,
    same_as_cli: Optional[bool] = None,
) -> None:
    print(title(heading))
    if install.executable is not None:
        print(f"  Executable: {install.executable}")
    if install.resolved_executable is not None and (
        (
            install.executable is not None
            and Path(install.executable).is_symlink()
        )
        or (
            install.executable is not None
            and Path(install.executable).absolute() != install.resolved_executable
        )
    ):
        print(f"  Resolved executable: {install.resolved_executable}")
    if install.interpreter is not None:
        print(f"  Interpreter: {install.interpreter}")
    if install.environment is not None:
        print(f"  Environment: {install.environment}")
    print(f"  Installation: {_installation_label(install)}")
    if install.source:
        print(f"  Install source: {highlight(install.source)}")
    if install.version:
        print(f"  Installed version: {install.version}")
    print(f"  Installed revision: {install.revision or 'unknown'}")
    if github.default_branch:
        latest = github.latest_sha or "unavailable"
        print(f"  Latest GitHub revision ({github.default_branch}): {latest}")
    else:
        print(f"  Latest GitHub revision: {github.latest_sha or 'unavailable'}")
    if service is not None:
        if service.exists:
            print(f"  Service: {service.path}")
            if service.exec_start:
                print(f"  ExecStart: {' '.join(service.exec_start)}")
        else:
            print(f"  Service: not installed ({service.path} missing)")
    if same_as_cli is not None:
        print(f"  Same environment as ref-cli: {'yes' if same_as_cli else 'no'}")
    status_colour = {
        "current": success,
        "outdated": warning,
        "not-detected": warning,
    }.get(install.status, info)
    print(f"  Status: {status_colour(install.status)} - {install.status_detail}")
    for note in install.notes:
        print(dim(f"  Note: {note}"))


def _print_no_service(service: ServiceInfo) -> None:
    print(title("ref-api"))
    if service.exists:
        print(f"  Service: {service.path}")
        print(f"  Service detail: {service.error or 'no usable ExecStart found'}")
        print("  Installation: not detected")
        print("  Status: unknown - the service environment could not be inspected")
        return
    print(f"  Service: not installed ({service.path} missing)")
    if service.error:
        print(f"  Service detail: {service.error}")
    ref_api_on_path = shutil.which("ref-api")
    if ref_api_on_path:
        print(
            dim(
                "  Note: a ref-api executable exists at "
                f"{ref_api_on_path}, but no user service unit was found; this is "
                "not assumed to be a managed installation."
            )
        )
    print("  Installation: not detected")
    print("  Status: not installed")


def _unique_installations(
    installs: Iterable[Installation],
) -> List[Installation]:
    unique: List[Installation] = []
    for install in installs:
        if any(
            _same_path(install.environment, existing.environment)
            for existing in unique
        ):
            continue
        unique.append(install)
    return unique


def _build_actions(
    cli: Installation,
    api: Optional[Installation],
    pipx_installs: List[Installation],
    github: GitHubState,
    service: ServiceInfo,
) -> Tuple[List[UpgradeAction], List[str]]:
    actions: List[UpgradeAction] = []
    unresolved: List[str] = []
    api_env = api.environment if api is not None else None
    service_exists = service.exists
    cli_api_required = cli.has_api_extra or _same_path(cli.environment, api_env)
    handled_environments: List[Optional[Path]] = []

    if cli.status == "outdated":
        commands, notes, problem = _upgrade_commands(
            cli,
            latest_sha=github.latest_sha,
            api_required=cli_api_required,
            repository=github.repository,
        )
        if problem:
            unresolved.append(f"{cli.role}: {problem}")
        else:
            restart = service_exists and _same_path(cli.environment, api_env)
            actions.append(
                UpgradeAction(
                    title=f"{cli.role} ({cli.environment})",
                    install=cli,
                    commands=commands,
                    notes=notes,
                    restart_service=restart,
                )
            )
        handled_environments.append(cli.environment)
    elif cli.status == "unknown":
        unresolved.append(f"{cli.role}: {cli.status_detail}")
    handled_environments.append(cli.environment)

    if api is not None and api.status == "outdated":
        if _same_path(api.environment, cli.environment):
            if cli.status != "outdated":
                unresolved.append(
                    "ref-api shares the ref-cli environment, but its status differs; "
                    "inspect the environment before changing it."
                )
        else:
            commands, notes, problem = _upgrade_commands(
                api,
                latest_sha=github.latest_sha,
                api_required=True,
                repository=github.repository,
            )
            if problem:
                unresolved.append(f"ref-api: {problem}")
            else:
                actions.append(
                    UpgradeAction(
                        title=f"ref-api ({api.environment})",
                        install=api,
                        commands=commands,
                        notes=notes,
                        restart_service=service_exists,
                    )
                )
            handled_environments.append(api.environment)
    elif api is not None and api.status == "unknown":
        unresolved.append(f"ref-api: {api.status_detail}")

    for install in pipx_installs:
        if any(
            _same_path(install.environment, handled)
            for handled in handled_environments
        ):
            continue
        if install.status == "outdated":
            commands, notes, problem = _upgrade_commands(
                install,
                latest_sha=github.latest_sha,
                api_required=install.has_api_extra,
                repository=github.repository,
            )
            if problem:
                unresolved.append(f"{install.role}: {problem}")
            else:
                notes = list(notes)
                if service_exists and not _same_path(install.environment, api_env):
                    notes.append(
                        "This pipx environment is not used by ref-api.service, so "
                        "this change does not require a ref-api restart."
                    )
                actions.append(
                    UpgradeAction(
                        title=f"{install.role} ({install.environment})",
                        install=install,
                        commands=commands,
                        notes=notes,
                        restart_service=service_exists and _same_path(
                            install.environment, api_env
                        ),
                    )
                )
        elif install.status == "unknown":
            unresolved.append(f"{install.role}: {install.status_detail}")
    return actions, unresolved


def report_upgrade_instructions(
    *,
    cli_environment: Optional[Path] = None,
    prefix: Optional[str] = None,
    cli_executable: Optional[Path] = None,
    systemd_unit: Optional[Path] = None,
    pipx_home: Optional[Path] = None,
    github_state: Optional[GitHubState] = None,
    github_fetcher: Optional[Callable[[str, float], Any]] = None,
    repository: str = DEFAULT_REPOSITORY,
    timeout: float = DEFAULT_TIMEOUT,
) -> int:
    """Inspect installations and print read-only upgrade instructions."""
    if cli_environment is None and prefix is not None:
        cli_environment = Path(prefix)

    github = github_state or check_github(
        repository=repository, timeout=timeout, fetcher=github_fetcher
    )
    cli = detect_cli_installation(
        cli_environment=cli_environment,
        cli_executable=cli_executable,
    )
    service = detect_service(systemd_unit)
    api, service = detect_api_installation(service=service)
    all_pipx = discover_pipx_installations(pipx_home=pipx_home)

    evaluate_status(cli, github)
    if api is not None:
        evaluate_status(api, github)

    separate_pipx: List[Installation] = []
    for install in _unique_installations(all_pipx):
        if _same_path(install.environment, cli.environment):
            continue
        if api is not None and _same_path(install.environment, api.environment):
            continue
        evaluate_status(install, github)
        separate_pipx.append(install)

    _print_installation("ref-cli", cli, github)
    for install in separate_pipx:
        _print_installation(
            f"pipx ref-cli ({install.environment})",
            install,
            github,
        )

    if api is None:
        _print_no_service(service)
    else:
        _print_installation(
            "ref-api",
            api,
            github,
            service=service,
            same_as_cli=_same_path(api.environment, cli.environment),
        )
        if service.error:
            print(dim(f"  Note: {service.error}"))

    actions, unresolved = _build_actions(
        cli, api, separate_pipx, github, service
    )

    print(title("Upgrade instructions"))
    if actions:
        index = 0
        for action in actions:
            index += 1
            print(f"{index}. {action.title}")
            for note in action.notes:
                print(dim(f"   Note: {note}"))
            for command in action.commands:
                print(f"   {command}")
            if action.restart_service:
                print("   systemctl --user restart ref-api.service")
                print(
                    dim(
                        "   Note: restart ref-api.service after the environment used "
                        "by its ExecStart changes."
                    )
                )
    else:
        if unresolved:
            print(
                warning(
                    "No upgrade commands are recommended because some statuses "
                    "could not be determined:"
                )
            )
            for item in unresolved:
                print(f"  - {item}")
        else:
            print(success("Nothing to do: all detected installations are current."))

    if unresolved and actions:
        print(warning("Also unresolved:"))
        for item in unresolved:
            print(f"  - {item}")

    print(title("Verification"))
    print("  ref --version")
    if separate_pipx or cli.pipx_managed:
        print("  pipx list")
        print("  pipx runpip ref-cli show ref-cli")
    if api is not None:
        python = _venv_python(api)
        if python:
            print(
                f"  {shlex.quote(python)} -c "
                "\"import importlib.metadata as m; "
                "print(m.version('ref-cli'))\""
            )
        if service.exists:
            print("  systemctl --user status ref-api.service")
            if service.health_url:
                print(f"  curl -fsS {service.health_url}")

    if actions:
        print(title("Rollback (only if the upgrade fails)"))
        print("  # Reinstall the revision that was running before this upgrade:")
        for action in actions:
            install = action.install
            api_required = (
                install.role == "ref-api"
                or install.has_api_extra
                or _same_path(install.environment, api.environment if api else None)
            )
            command = _rollback_command(install, api_required=api_required)
            if command:
                print(f"  {command}")
            else:
                print(
                    dim(
                        "  # No exact rollback command is available for "
                        f"{install.role}; record its installed revision "
                        f"({install.revision or 'unknown'}) before upgrading."
                    )
                )
        print(
            dim(
                "  Do not restore an older references.md snapshot over newer data "
                "unless corruption is confirmed; package rollback should normally "
                "keep the current archive."
            )
        )
    return 0
