"""Tests for ref --upgrade instruction helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ref_cli import upgrade


def _metadata(
    package_or_url: str,
    *,
    version: str = "1.2.3",
    injected_api: bool = False,
) -> dict:
    data = {
        "main_package": {
            "package_or_url": package_or_url,
            "package_version": version,
        },
        "injected_packages": {},
    }
    if injected_api:
        data["injected_packages"]["ref-cli"] = {
            "package": "ref-cli",
            "package_or_url": "ref-cli[api]",
            "package_version": version,
        }
    return data


def test_classify_local_path() -> None:
    assert (
        upgrade.classify_upgrade_command("/opt/md2/git/personal/ref")
        == "pipx install --force /opt/md2/git/personal/ref"
    )


def test_classify_git_url() -> None:
    url = "git+https://github.com/draeician/ref.git@main"
    assert upgrade.classify_upgrade_command(url) == f"pipx install --force '{url}'"


def test_classify_pypi() -> None:
    assert upgrade.classify_upgrade_command("ref-cli") == "pipx upgrade ref-cli"
    assert upgrade.classify_upgrade_command("ref-cli==1.6.11") == "pipx upgrade ref-cli"


def test_build_upgrade_steps_local(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(upgrade, "_fastapi_importable", lambda: False)
    unit = tmp_path / "missing.service"
    source, version, commands = upgrade.build_upgrade_steps(
        _metadata("/opt/md2/git/personal/ref", version="9.0.0"),
        systemd_unit=unit,
    )
    assert source == "/opt/md2/git/personal/ref"
    assert version == "9.0.0"
    assert commands == ["pipx install --force /opt/md2/git/personal/ref"]


def test_build_upgrade_steps_with_api_and_unit(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(upgrade, "_fastapi_importable", lambda: False)
    unit = tmp_path / "ref-api.service"
    unit.write_text("[Unit]\n", encoding="utf-8")
    _, _, commands = upgrade.build_upgrade_steps(
        _metadata(
            "/opt/md2/git/personal/ref",
            injected_api=True,
        ),
        systemd_unit=unit,
    )
    assert commands == [
        "pipx install --force /opt/md2/git/personal/ref",
        "pipx inject ref-cli 'ref-cli[api]'",
        "systemctl --user restart ref-api",
    ]


def test_report_upgrade_instructions_local(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade, "_fastapi_importable", lambda: False)
    meta = tmp_path / "pipx_metadata.json"
    meta.write_text(
        json.dumps(_metadata("/opt/md2/git/personal/ref")),
        encoding="utf-8",
    )
    unit = tmp_path / "no-unit"
    code = upgrade.report_upgrade_instructions(
        prefix=str(tmp_path),
        systemd_unit=unit,
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Install source:" in out
    assert "/opt/md2/git/personal/ref" in out
    assert "pipx install --force /opt/md2/git/personal/ref" in out


def test_report_upgrade_instructions_git(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade, "_fastapi_importable", lambda: False)
    url = "git+https://github.com/draeician/ref.git"
    (tmp_path / "pipx_metadata.json").write_text(
        json.dumps(_metadata(url)),
        encoding="utf-8",
    )
    code = upgrade.report_upgrade_instructions(
        prefix=str(tmp_path),
        systemd_unit=tmp_path / "missing",
    )
    assert code == 0
    assert f"pipx install --force '{url}'" in capsys.readouterr().out


def test_report_upgrade_instructions_pypi(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(upgrade, "_fastapi_importable", lambda: False)
    (tmp_path / "pipx_metadata.json").write_text(
        json.dumps(_metadata("ref-cli")),
        encoding="utf-8",
    )
    code = upgrade.report_upgrade_instructions(
        prefix=str(tmp_path),
        systemd_unit=tmp_path / "missing",
    )
    assert code == 0
    assert "pipx upgrade ref-cli" in capsys.readouterr().out


def test_report_upgrade_instructions_missing_metadata(tmp_path: Path, capsys) -> None:
    code = upgrade.report_upgrade_instructions(
        prefix=str(tmp_path),
        systemd_unit=tmp_path / "missing",
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "not detected as a pipx venv" in out


def test_report_upgrade_instructions_corrupt_metadata(tmp_path: Path, capsys) -> None:
    (tmp_path / "pipx_metadata.json").write_text("{not-json", encoding="utf-8")
    code = upgrade.report_upgrade_instructions(
        prefix=str(tmp_path),
        systemd_unit=tmp_path / "missing",
    )
    assert code == 1
    assert "Could not read pipx metadata" in capsys.readouterr().out
