import os
import sys

import pytest

TEST_ROOT = os.path.dirname(__file__)
PROJECT_SRC = os.path.abspath(os.path.join(TEST_ROOT, "..", "src"))

if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)


@pytest.fixture(autouse=True)
def _disable_transcript_reconciler_by_default(monkeypatch):
    """Keep test app lifespans away from the real archive/queue.

    Reconciliation tests enable the feature explicitly with their own temporary
    archive and queue.
    """
    monkeypatch.setenv("REF_TRANSCRIPT_RECONCILE_ENABLED", "false")
