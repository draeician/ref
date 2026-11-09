"""Regression tests for the read-only ``ref --upgrade`` command."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from urllib import error as urlerror

import pytest

from ref_cli import cli, server_install, upgrade

LATEST_SHA = "80c6e379106a73c047cd517e56207bc62d558d7f"
OLD_SHA = "5565ab59d0123456789012345678901234567890"
INSTALLED_VERSION = "1.6.12b1.dev129+g80c6e3791"
OLD_VERSION = "1.6.12b1.dev117+g5565ab59d"
GIT_URL = "https://github.com/draeician/ref.git"


# ---------------------------------------------------------------------------
# Fixtures/helpers
# ---------------------------------------------------------------------------


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _clean(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_venv(
    root: Path,
    *,
    version: str = INSTALLED_VERSION,
    sha: str | None = LATEST_SHA,
    source: str = GIT_URL,
    source_kind: str = "git",
    api: bool = True,
    editable: bool = False,
    pipx_metadata: dict | None = None,
    with_dist_info: bool = True,
) -> Path:
    """Create a fake Python virtualenv with ref-cli package metadata."""
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write(root / "pyvenv.cfg", "home = /usr/bin\nversion = 3.12.0\n")
    _write(bin_dir / "python", "#!/usr/bin/env python3\n")
    _write(bin_dir / "ref", "#!/usr/bin/env python3\n")
    _write(bin_dir / "ref-api", "#!/usr/bin/env python3\n")

    site = root / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    if with_dist_info:
        dist = site / f"ref_cli-{version}.dist-info"
        _write(
            dist / "METADATA",
            f"Metadata-Version: 2.1\nName: ref-cli\nVersion: {version}\n\n",
        )
        _write(dist / "INSTALLER", "pip\n")
        direct_url = None
        if source_kind == "git":
            direct_url = {
                "url": source,
                "vcs_info": {
                    "vcs": "git",
                    "commit_id": sha,
                    "requested_revision": "main",
                },
            }
        elif source_kind in ("local", "editable"):
            direct_url = {
                "url": Path(source).as_uri() if Path(source).is_absolute() else source,
                "dir_info": {"editable": editable},
            }
        if direct_url is not None:
            _write(dist / "direct_url.json", json.dumps(direct_url))
        _write(
            site / "ref_cli" / "_version.py",
            f"commit_id = {sha!r}\n" if sha else "commit_id = None\n",
        )

    if api:
        for name in ("fastapi", "uvicorn"):
            _write(
                site / f"{name}-0.110.0.dist-info" / "METADATA",
                f"Metadata-Version: 2.1\nName: {name}\nVersion: 0.110.0\n\n",
            )

    if pipx_metadata is not None:
        _write(root / "pipx_metadata.json", json.dumps(pipx_metadata))
    return root


def _make_pipx_install(
    home: Path,
    name: str = "ref-cli",
    *,
    version: str = OLD_VERSION,
    sha: str | None = OLD_SHA,
    package_or_url: str = f"git+{GIT_URL}@main",
    api_injected: bool = False,
    corrupt: bool = False,
) -> Path:
    venv = home / "venvs" / name
    metadata = {
        "main_package": {
            "package": "ref-cli",
            "package_or_url": package_or_url,
            "package_version": version,
        },
        "injected_packages": {},
    }
    if api_injected:
        metadata["injected_packages"]["ref-cli"] = {
            "package": "ref-cli",
            "package_or_url": "ref-cli[api]",
            "package_version": version,
        }
    _make_venv(
        venv,
        version=version,
        sha=sha,
        source_kind="git",
        pipx_metadata=None,
    )
    if corrupt:
        _write(venv / "pipx_metadata.json", "{not-json")
    else:
        _write(venv / "pipx_metadata.json", json.dumps(metadata))
    return venv


def _unit(path: Path, executable: Path, *, host: str = "0.0.0.0", port: int = 8000) -> Path:
    _write(
        path,
        "[Unit]\nDescription=ref-api\n\n[Service]\n"
        f"ExecStart={executable} --host {host} --port {port}\n",
    )
    return path


def _args(**overrides):
    values = {
        "status": False,
        "upgrade": False,
        "install_server": False,
        "uninstall_server": False,
        "server_status": False,
        "url_dump": None,
        "server_host": "0.0.0.0",
        "server_port": 8000,
        "verbose": False,
        "debug": None,
        "edit": False,
    }
    values.update(overrides)
    return type("Args", (), values)()


def _report(tmp_path: Path, **kwargs) -> None:
    kwargs.setdefault("github_state", upgrade.GitHubState(
        default_branch="main", latest_sha=LATEST_SHA
    ))
    kwargs.setdefault("pipx_home", tmp_path / "no-pipx")
    upgrade.report_upgrade_instructions(**kwargs)


# ---------------------------------------------------------------------------
# Topology detection
# ---------------------------------------------------------------------------


def test_minion_split_venv_topology(tmp_path: Path, capsys) -> None:
    service = _make_venv(tmp_path / "ref-services" / "ref-api", api=True)
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(pipx_home)
    unit = _unit(tmp_path / "ref-api.service", service / "bin" / "ref-api")
    launcher = tmp_path / "local-bin" / "ref"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(service / "bin" / "ref")

    _report(
        tmp_path,
        cli_environment=service,
        cli_executable=launcher,
        systemd_unit=unit,
        pipx_home=pipx_home,
    )

    out = _clean(capsys.readouterr().out)
    assert "ref-cli" in out
    assert "ref-api" in out
    assert "Resolved executable:" in out
    assert f"Latest GitHub revision (main): {LATEST_SHA}" in out
    assert "pipx ref-cli" in out
    assert "Status: current" in out
    assert "Status: outdated" in out
    assert INSTALLED_VERSION in out
    assert OLD_VERSION in out
    # The dedicated service venv is current, so only the stale pipx install is
    # recommended for upgrade, and it does not require a service restart.
    assert f"pipx install --force git+{GIT_URL}@{LATEST_SHA}" in out
    assert "does not require a ref-api restart" in out
    assert "systemctl --user restart ref-api.service" not in out


def test_cli_executable_symlink_resolves_into_service_venv(tmp_path: Path) -> None:
    service = _make_venv(tmp_path / "service", api=True)
    launcher = tmp_path / "bin" / "ref"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(service / "bin" / "ref")

    install = upgrade.detect_cli_installation(
        cli_environment=service, cli_executable=launcher
    )

    assert install.environment == service
    assert install.resolved_executable == (service / "bin" / "ref").resolve()
    assert any("symlink resolves" in note for note in install.notes)


def test_separate_pipx_managed_ref_cli_is_detected(tmp_path: Path) -> None:
    cli_env = _make_venv(
        tmp_path / "cli-env", version=INSTALLED_VERSION, sha=LATEST_SHA
    )
    pipx_home = tmp_path / "pipx"
    pipx_venv = _make_pipx_install(pipx_home)
    unit = _unit(tmp_path / "ref-api.service", cli_env / "bin" / "ref-api")

    installs = upgrade.discover_pipx_installations(pipx_home=pipx_home)
    assert [install.environment for install in installs] == [pipx_venv]

    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=unit,
        pipx_home=pipx_home,
    )


def test_github_vcs_installation_metadata(tmp_path: Path) -> None:
    env = _make_venv(tmp_path / "env", source_kind="git")
    install = upgrade.detect_installation("ref-cli", env)

    assert install.source == f"git+{GIT_URL}"
    assert install.source_kind == "git"
    assert install.revision == LATEST_SHA
    assert install.version == INSTALLED_VERSION


def test_local_repository_installation_is_detected(tmp_path: Path) -> None:
    repo = tmp_path / "local-repo"
    repo.mkdir()
    env = _make_venv(tmp_path / "env", source=str(repo), source_kind="local")
    install = upgrade.detect_installation("ref-cli", env)

    assert install.source == str(repo)
    assert install.source_kind == "local"


def test_local_repository_upgrade_command_uses_the_environment_python(
    tmp_path: Path, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = _make_venv(
        tmp_path / "env",
        version=OLD_VERSION,
        sha=OLD_SHA,
        source=str(repo),
        source_kind="local",
        api=True,
    )
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
    )

    out = _clean(capsys.readouterr().out)
    assert f"{env / 'bin' / 'python'} -m pip install --upgrade" in out
    assert f"{repo}[api]" in out
    assert f"checked out at {LATEST_SHA}" in out


def test_local_wheel_artifact_is_not_treated_as_a_repository(
    tmp_path: Path, capsys
) -> None:
    wheel = tmp_path / "dist" / "ref_cli-1.6.12-py3-none-any.whl"
    _write(wheel, "wheel")
    env = _make_venv(
        tmp_path / "env",
        version=OLD_VERSION,
        sha=OLD_SHA,
        source=str(wheel),
        source_kind="local",
        api=True,
    )
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
    )

    out = _clean(capsys.readouterr().out)
    assert "local artifact" in out
    assert "does not record the Git repository" in out
    assert "ref-cli[api] @ git+" in out
    # The stale artifact path is never recommended as an upgrade target.
    assert f"pip install --upgrade {wheel}" not in out


def test_pypi_pipx_installation_is_detected(tmp_path: Path) -> None:
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(
        pipx_home,
        version="1.6.11",
        sha=None,
        package_or_url="ref-cli",
    )
    installs = upgrade.discover_pipx_installations(pipx_home=pipx_home)

    assert len(installs) == 1
    assert installs[0].source_kind == "pipx-pypi"
    assert installs[0].source == "ref-cli"
    assert installs[0].version == "1.6.11"


def test_pipx_metadata_is_read_without_a_pipx_executable(
    tmp_path: Path, monkeypatch
) -> None:
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(pipx_home)
    monkeypatch.setattr(upgrade.shutil, "which", lambda name: None)

    installs = upgrade.discover_pipx_installations(pipx_home=pipx_home)

    assert len(installs) == 1
    assert installs[0].pipx_managed is True


def test_missing_pipx_metadata_explains_unknown_provenance(tmp_path: Path, capsys) -> None:
    env = _make_venv(
        tmp_path / "env",
        with_dist_info=False,
        pipx_metadata=None,
        api=False,
    )
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
    )

    out = _clean(capsys.readouterr().out)
    assert "Installation source could not be determined" in out
    assert "No upgrade commands are recommended" in out
    assert "pipx install" not in out
    assert "pip install" not in out


def test_corrupt_pipx_metadata_does_not_crash(tmp_path: Path, capsys) -> None:
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(pipx_home, corrupt=True)
    cli_env = _make_venv(tmp_path / "cli-env", api=False)
    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
        pipx_home=pipx_home,
    )

    out = _clean(capsys.readouterr().out)
    assert "Could not read pipx metadata" in out
    assert "pipx ref-cli" in out


def test_missing_ref_api_service_is_not_invented(tmp_path: Path, capsys) -> None:
    env = _make_venv(tmp_path / "env", api=True)
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
    )

    out = _clean(capsys.readouterr().out)
    assert "Service: not installed" in out
    assert "ref-api" in out
    assert "systemctl --user restart" not in out


def test_unreadable_service_unit_is_not_reported_as_missing(
    tmp_path: Path, capsys
) -> None:
    env = _make_venv(tmp_path / "env", api=False)
    unit = tmp_path / "ref-api.service"
    _write(unit, "[Unit]\nDescription=broken\n")
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=unit,
    )

    out = _clean(capsys.readouterr().out)
    assert f"Service: {unit}" in out
    assert "No ExecStart line found" in out
    assert "Status: unknown" in out


def test_dedicated_ref_api_virtualenv_is_inspected(tmp_path: Path, capsys) -> None:
    cli_env = _make_venv(tmp_path / "cli-env", version=INSTALLED_VERSION, sha=LATEST_SHA)
    api_env = _make_venv(
        tmp_path / "api-env", version=OLD_VERSION, sha=OLD_SHA, api=True
    )
    unit = _unit(tmp_path / "ref-api.service", api_env / "bin" / "ref-api")
    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=unit,
    )

    out = _clean(capsys.readouterr().out)
    assert "Service:" in out
    assert f"ExecStart: {api_env / 'bin' / 'ref-api'} --host 0.0.0.0 --port 8000" in out
    assert "Same environment as ref-cli: no" in out
    assert "ref-api (" in out
    assert "systemctl --user restart ref-api.service" in out


def test_cli_and_api_different_versions_only_api_outdated(tmp_path: Path, capsys) -> None:
    cli_env = _make_venv(tmp_path / "cli-env", version=INSTALLED_VERSION, sha=LATEST_SHA)
    api_env = _make_venv(tmp_path / "api-env", version=OLD_VERSION, sha=OLD_SHA)
    unit = _unit(tmp_path / "ref-api.service", api_env / "bin" / "ref-api")
    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=unit,
    )

    out = _clean(capsys.readouterr().out)
    assert "Status: current" in out
    assert "Status: outdated" in out
    assert "1. ref-api (" in out
    assert "Nothing to do" not in out


def test_api_dependencies_are_retained_in_service_upgrade(tmp_path: Path, capsys) -> None:
    cli_env = _make_venv(tmp_path / "cli-env", version=INSTALLED_VERSION, sha=LATEST_SHA)
    api_env = _make_venv(tmp_path / "api-env", version=OLD_VERSION, sha=OLD_SHA)
    unit = _unit(tmp_path / "ref-api.service", api_env / "bin" / "ref-api")
    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=unit,
    )

    out = _clean(capsys.readouterr().out)
    assert "ref-cli[api] @ git+" in out
    assert f"@{LATEST_SHA}" in out


# ---------------------------------------------------------------------------
# GitHub and comparison behaviour
# ---------------------------------------------------------------------------


def test_github_unavailable_never_claims_current(tmp_path: Path, capsys) -> None:
    env = _make_venv(tmp_path / "env")
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
        github_state=upgrade.GitHubState(error="GitHub unavailable: offline"),
    )

    out = _clean(capsys.readouterr().out)
    assert "Latest GitHub revision: unavailable" in out
    assert "GitHub lookup failed" in out
    assert "Status: unknown" in out
    assert "pipx install" not in out
    assert "pip install" not in out


def test_github_rate_limit_and_timeout_are_reported() -> None:
    def rate_limited(url: str, timeout: float):
        raise upgrade.GitHubError("GitHub API rate limit exceeded")

    def timed_out(url: str, timeout: float):
        raise upgrade.GitHubError("GitHub request timed out")

    limited = upgrade.check_github(fetcher=rate_limited)
    slow = upgrade.check_github(fetcher=timed_out)
    assert "rate limit" in (limited.error or "").lower()
    assert "timed out" in (slow.error or "").lower()


def test_github_http_rate_limit_is_translated(monkeypatch) -> None:
    def raise_http(*args, **kwargs):
        raise urlerror.HTTPError(
            "https://api.github.com/repos/draeician/ref",
            429,
            "Too Many Requests",
            {},
            None,
        )

    monkeypatch.setattr(upgrade.urlrequest, "urlopen", raise_http)
    with pytest.raises(upgrade.GitHubError, match="rate limit"):
        upgrade._github_get_json("https://api.github.com/repos/draeician/ref")


def test_github_network_timeout_is_translated(monkeypatch) -> None:
    def raise_timeout(*args, **kwargs):
        raise urlerror.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(upgrade.urlrequest, "urlopen", raise_timeout)
    with pytest.raises(upgrade.GitHubError, match="timed out"):
        upgrade._github_get_json("https://api.github.com/repos/draeician/ref")


@pytest.mark.parametrize(
    "installed,latest,expected",
    [
        ("80c6e3791", LATEST_SHA, "current"),
        ("80c6e379106a73c047cd517e56207bc62d558d7f", LATEST_SHA, "current"),
        (OLD_SHA[:9], LATEST_SHA, "outdated"),
        ("80c6", LATEST_SHA, "unknown"),
        (None, LATEST_SHA, "unknown"),
        ("not-a-sha", LATEST_SHA, "unknown"),
    ],
)
def test_revision_comparison_handles_abbreviations(
    installed, latest, expected
) -> None:
    assert upgrade.compare_revisions(installed, latest) == expected


def test_both_installations_current(tmp_path: Path, capsys) -> None:
    service = _make_venv(tmp_path / "service", api=True)
    unit = _unit(tmp_path / "ref-api.service", service / "bin" / "ref-api")
    _report(
        tmp_path,
        cli_environment=service,
        cli_executable=service / "bin" / "ref",
        systemd_unit=unit,
    )

    out = _clean(capsys.readouterr().out)
    assert out.count("Status: current") >= 2
    assert "Nothing to do: all detected installations are current." in out
    assert "pipx install" not in out
    assert "pip install" not in out
    assert "systemctl --user restart" not in out


def test_only_one_installation_outdated(tmp_path: Path, capsys) -> None:
    cli_env = _make_venv(tmp_path / "cli-env", version=INSTALLED_VERSION, sha=LATEST_SHA)
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(pipx_home)
    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
        pipx_home=pipx_home,
    )

    out = _clean(capsys.readouterr().out)
    assert "Status: current" in out
    assert "Status: outdated" in out
    assert "1. pipx:ref-cli" in out
    assert "Nothing to do" not in out


def test_unknown_installation_provenance_has_no_invented_command(
    tmp_path: Path, capsys
) -> None:
    env = _make_venv(
        tmp_path / "env",
        version=OLD_VERSION,
        sha=OLD_SHA,
        source_kind="none",
        api=False,
    )
    _report(
        tmp_path,
        cli_environment=env,
        cli_executable=env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
    )

    out = _clean(capsys.readouterr().out)
    assert "no safe upgrade command" in out
    assert "pip install" not in out
    assert "pipx install" not in out


# ---------------------------------------------------------------------------
# Read-only guarantees and actual CLI dispatch
# ---------------------------------------------------------------------------


def test_upgrade_command_performs_no_mutations(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    cli_env = _make_venv(tmp_path / "cli-env", version=OLD_VERSION, sha=OLD_SHA)
    pipx_home = tmp_path / "pipx"
    _make_pipx_install(pipx_home)

    def forbidden(*args, **kwargs):
        raise AssertionError("ref --upgrade must not execute commands")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(os, "popen", forbidden)

    _report(
        tmp_path,
        cli_environment=cli_env,
        cli_executable=cli_env / "bin" / "ref",
        systemd_unit=tmp_path / "missing.service",
        pipx_home=pipx_home,
    )

    out = _clean(capsys.readouterr().out)
    assert "pip install --upgrade" in out
    assert "pipx install --force" in out


def test_automatic_upgrade_path_is_removed() -> None:
    assert not hasattr(upgrade, "perform_upgrade")


def test_upgrade_import_does_not_create_archive_logs(tmp_path: Path) -> None:
    """A fresh ``ref --upgrade`` process must not write application data."""
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    src = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(src)
    code = (
        "import sys; sys.argv = ['ref', '--upgrade']; "
        "import ref_cli.cli; print('imported')"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert not (home / "references").exists()
    assert not (home / ".config" / "ref").exists()


def test_main_dispatches_upgrade_read_only(monkeypatch) -> None:
    monkeypatch.setattr(cli, "parse_arguments", lambda: _args(upgrade=True))

    def forbidden(*args, **kwargs):
        raise AssertionError("archive bootstrap must not run for --upgrade")

    monkeypatch.setattr(cli, "ensure_path_exists", forbidden)
    import ref_cli.references_format as references_format

    monkeypatch.setattr(references_format, "ensure_references_migrated", forbidden)

    with patch(
        "ref_cli.upgrade.report_upgrade_instructions", return_value=7
    ) as mock_report:
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 7
    mock_report.assert_called_once_with()


def test_main_upgrade_runs_full_report_without_subprocess(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    env = _make_venv(tmp_path / "env")
    unit = _unit(tmp_path / "ref-api.service", env / "bin" / "ref-api")
    monkeypatch.setattr("sys.argv", ["ref", "--upgrade"])
    monkeypatch.setattr(
        upgrade,
        "check_github",
        lambda **kwargs: upgrade.GitHubState(
            default_branch="main", latest_sha=LATEST_SHA
        ),
    )
    monkeypatch.setattr(
        upgrade,
        "detect_cli_installation",
        lambda **kwargs: upgrade.detect_installation(
            "ref-cli", env, executable=env / "bin" / "ref"
        ),
    )
    original_detect_service = upgrade.detect_service
    monkeypatch.setattr(
        upgrade,
        "detect_service",
        lambda systemd_unit=None: original_detect_service(unit),
    )
    monkeypatch.setattr(
        upgrade,
        "discover_pipx_installations",
        lambda pipx_home=None: [],
    )
    monkeypatch.setattr(
        server_install, "SYSTEMD_UNIT", tmp_path / "missing.service"
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("ref --upgrade must not execute commands")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = _clean(capsys.readouterr().out)
    assert "ref-cli" in out
    assert "Upgrade instructions" in out
    assert "Verification" in out


def test_parse_arguments_accepts_upgrade_flag(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["ref", "--upgrade"])
    args = cli.parse_arguments()
    assert args.upgrade is True


# ---------------------------------------------------------------------------
# Direct helper coverage retained for compatibility
# ---------------------------------------------------------------------------


def test_load_pipx_metadata_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "pipx_metadata.json"
    _write(path, "[]")
    with pytest.raises(ValueError):
        upgrade.load_pipx_metadata(path)


def test_pin_git_source_preserves_repository() -> None:
    assert (
        upgrade.pin_git_source(f"git+{GIT_URL}@main", LATEST_SHA)
        == f"git+{GIT_URL}@{LATEST_SHA}"
    )
    assert (
        upgrade.pin_git_source(f"git+{GIT_URL}", LATEST_SHA)
        == f"git+{GIT_URL}@{LATEST_SHA}"
    )
