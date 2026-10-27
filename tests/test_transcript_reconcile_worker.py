"""Lifecycle tests for the ref-api transcript reconciliation worker."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from ref_api import service


@pytest.fixture(autouse=True)
def _isolated_reconcile_config(monkeypatch):
    monkeypatch.setattr(service, "_reconcile_config", lambda: {})
    monkeypatch.delenv("REF_TRANSCRIPT_RECONCILE_ENABLED", raising=False)
    yield
    service.stop_transcript_reconciler(timeout=2)


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_startup_pass_runs_immediately_and_stops(monkeypatch):
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "true")
    ran = threading.Event()
    calls = []

    def reconcile_once():
        calls.append(time.monotonic())
        ran.set()

    assert service.start_transcript_reconciler(
        interval_seconds=60, reconcile_once=reconcile_once
    )
    assert ran.wait(timeout=2)
    service.stop_transcript_reconciler(timeout=2)

    assert len(calls) >= 1
    assert service._reconcile_worker is None


def test_periodic_execution(monkeypatch):
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "true")
    calls = []
    second = threading.Event()

    def reconcile_once():
        calls.append(time.monotonic())
        if len(calls) >= 2:
            second.set()

    assert service.start_transcript_reconciler(
        interval_seconds=0.02, reconcile_once=reconcile_once
    )
    assert second.wait(timeout=2)
    service.stop_transcript_reconciler(timeout=2)

    assert len(calls) >= 2


def test_worker_survives_reconciliation_errors(monkeypatch):
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "true")
    calls = []
    second = threading.Event()

    def reconcile_once():
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        second.set()

    assert service.start_transcript_reconciler(
        interval_seconds=0.02, reconcile_once=reconcile_once
    )
    assert second.wait(timeout=2)
    service.stop_transcript_reconciler(timeout=2)

    assert len(calls) >= 2


def test_disabled_setting_does_not_start(monkeypatch):
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "false")
    calls = []

    assert not service.start_transcript_reconciler(
        interval_seconds=0.02, reconcile_once=lambda: calls.append(1)
    )
    time.sleep(0.05)

    assert calls == []
    assert service._reconcile_worker is None


def test_stop_is_idempotent(monkeypatch):
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "true")
    assert service.start_transcript_reconciler(
        interval_seconds=60, reconcile_once=lambda: None
    )
    service.stop_transcript_reconciler(timeout=2)
    service.stop_transcript_reconciler(timeout=2)
    assert service._reconcile_worker is None


def test_application_lifespan_starts_and_stops_reconciler():
    from fastapi.testclient import TestClient

    from ref_api.app import create_app

    started = []
    stopped = []

    with (
        patch("ref_api.app._bootstrap_archive"),
        patch.object(
            service,
            "start_transcript_reconciler",
            side_effect=lambda: started.append(True),
        ),
        patch.object(
            service,
            "stop_transcript_reconciler",
            side_effect=lambda **kwargs: stopped.append(True),
        ),
    ):
        with TestClient(create_app()):
            assert started == [True]
            assert stopped == []

    assert stopped == [True]
