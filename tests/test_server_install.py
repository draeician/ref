"""Tests for ref --install-server / server_install module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ref_cli import server_install


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    config_dir = tmp_path / ".config" / "ref"
    systemd_dir = tmp_path / ".config" / "systemd" / "user"
    monkeypatch.setattr(server_install, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(server_install, "CONFIG_FILE", config_dir / "config.yaml")
    monkeypatch.setattr(server_install, "REF_API_ENV", config_dir / "ref-api.env")
    monkeypatch.setattr(
        server_install, "REF_API_ENV_TEMPLATE", config_dir / "ref-api.env.template"
    )
    monkeypatch.setattr(server_install, "SYSTEMD_USER_DIR", systemd_dir)
    monkeypatch.setattr(server_install, "SYSTEMD_UNIT", systemd_dir / "ref-api.service")
    return tmp_path


def test_bootstrap_config_dir_creates_documented_template(config_home):
    created: list[str] = []
    server_install.bootstrap_config_dir(created=created)

    config_file = server_install.CONFIG_FILE
    assert config_file.exists()
    text = config_file.read_text(encoding="utf-8")
    assert "api_url:" in text
    assert "ref-api client mode" in text
    assert str(config_file) in created
    assert server_install.REF_API_ENV_TEMPLATE.exists()


def test_set_local_api_url_updates_null(config_home):
    server_install.bootstrap_config_dir()
    assert server_install.set_local_api_url("0.0.0.0", 8000) is True
    text = server_install.CONFIG_FILE.read_text(encoding="utf-8")
    assert "api_url: http://127.0.0.1:8000" in text


def test_write_systemd_unit(config_home):
    unit = server_install.write_systemd_unit("/usr/bin/ref-api", "0.0.0.0", 9000)
    body = unit.read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/ref-api --host 0.0.0.0 --port 9000" in body
    assert str(server_install.REF_API_ENV) in body


def test_install_server_happy_path(config_home, monkeypatch, capsys):
    monkeypatch.setattr(server_install, "_api_deps_available", lambda: True)
    monkeypatch.setattr(server_install, "resolve_ref_api_binary", lambda: "/usr/bin/ref-api")
    monkeypatch.setattr(server_install, "_systemd_available", lambda: True)
    monkeypatch.setattr(server_install, "bootstrap_archive_paths", lambda: None)

    def fake_systemctl(*args):
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr(server_install, "_run_systemctl", fake_systemctl)

    code = server_install.install_server(host="0.0.0.0", port=8000)
    assert code == 0
    assert server_install.SYSTEMD_UNIT.exists()
    assert "http://127.0.0.1:8000" in server_install.CONFIG_FILE.read_text(encoding="utf-8")


def test_uninstall_server_removes_unit(config_home):
    server_install.write_systemd_unit("/usr/bin/ref-api", "0.0.0.0", 8000)
    with patch.object(server_install, "_systemd_available", return_value=True):
        with patch.object(server_install, "_run_systemctl", return_value=MagicMock(returncode=0)):
            assert server_install.uninstall_server() == 0
    assert not server_install.SYSTEMD_UNIT.exists()
