"""Credential redaction regressions for diagnostics and logs.

Captured URLs can contain userinfo (``scheme://user:pass@host``) or token-like
query/fragment values.  Neither API responses nor log lines may echo them.
"""

from __future__ import annotations

import logging

import pytest

from ref_api import service
from ref_cli.capture import redact_credentials, sanitize_error_detail
from ref_cli.cli import log_error


@pytest.mark.parametrize(
    "value,secret",
    [
        ("https://alice:hunter2@example.org/path", "hunter2"),
        ("https://token-abc@example.org/path", "token-abc"),
        ("https://example.org/a?api_key=supersecret&x=1", "supersecret"),
        ("https://example.org/a?access_token=abc123&b=2", "abc123"),
        ("https://example.org/a?X-Amz-Signature=deadbeef&y=3", "deadbeef"),
        ("https://example.org/a#refresh_token=fragsecret", "fragsecret"),
        ("token=plain-secret in a message", "plain-secret"),
    ],
)
def test_redaction_hides_userinfo_and_token_values(value, secret):
    redacted = redact_credentials(value)
    assert secret not in redacted
    assert "***" in redacted


def test_sanitize_bounds_and_flattens_without_leaking():
    raw = "boom\nhttps://alice:hunter2@example.org/a?token=secret-value&ok=1"
    sanitized = sanitize_error_detail(raw)

    assert "\n" not in sanitized
    assert "hunter2" not in sanitized
    assert "secret-value" not in sanitized
    assert "https://***@example.org/a?token=***&ok=1" in sanitized


def test_log_error_redacts_userinfo_and_tokens(tmp_path, monkeypatch):
    """The error-log file and Python logging must both be sanitized."""
    from ref_cli import cli

    log_path = tmp_path / "errors.log"
    logger = logging.getLogger("ref_cli_errors")
    logger.handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    monkeypatch.setattr(cli, "error_logger", logger)

    log_error(
        "Capture",
        "https://alice:hunter2@example.org/private?api_key=supersecret",
        "failed with access_token=leaked",
    )

    logger.handlers[0].flush()
    text = log_path.read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert "supersecret" not in text
    assert "leaked" not in text
    assert "***" in text


def test_process_error_does_not_echo_url_credentials(monkeypatch, tmp_path):
    archive = tmp_path / "references.md"
    archive.write_text("# ref-references version=2\n", encoding="utf-8")
    monkeypatch.setattr(service.ref_cli, "UNIFIED", str(archive))
    monkeypatch.setattr(service.ref_cli, "BASE", str(tmp_path))
    monkeypatch.setattr(service.ref_cli, "load_config", lambda: {"skip_patterns": []})
    monkeypatch.setattr(service.ref_cli, "should_skip_url", lambda url, cfg: False)

    def boom(*args, **kwargs):
        raise RuntimeError(
            "provider rejected https://alice:hunter2@example.org/a?token=leaked"
        )

    monkeypatch.setattr(service.ref_cli, "process_url", boom)
    for name in ("_identity_store", "_identity_dir"):
        monkeypatch.setattr(service, name, None)

    result = service.process_one(
        "https://alice:hunter2@example.org/a?token=leaked"
    )

    assert result.status == "error"
    assert "hunter2" not in (result.error or "")
    assert "leaked" not in (result.error or "")
    assert "hunter2" not in result.output
    assert "https://***@example.org/a?token=***" in (result.error or "")
