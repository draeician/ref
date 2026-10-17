"""Deterministic fail-before/pass-after regressions for references.md integrity.

Blocker A: ``enrich_youtube_reference`` -> ``references_format.apply_row_updates``
rewrites the entire archive. Before the shared ``archive_lock`` was introduced,
that rewrite read the file, then (much later) rewrote it, so a concurrent append
or rewrite of a distinct row during the gap was silently clobbered.

These tests pause a realistic ``enrich_youtube_reference`` rewrite *between* its
read and its commit (inside the archive lock) while a second thread appends a
distinct row. The append must be blocked by the lock and, once the rewrite is
released, both rows must survive with correct metadata and no duplicates.
"""

from __future__ import annotations

import threading

import pytest

from ref_cli import cli as ref_cli
from ref_cli import enrichment
from ref_cli import references_format

VIDEO_ID = "XCUWrrmaNck"
VIDEO_URL = f"https://youtu.be/{VIDEO_ID}"
OTHER_URL = "https://example.org/other"


@pytest.fixture
def isolated_refs(monkeypatch, tmp_path):
    refs = tmp_path / "references.md"
    refs.write_text(
        "# ref-references version=2\n"
        f"2026-07-08T01:12:39|[{VIDEO_URL}]|(T)|Ch|YouTube\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ref_cli, "UNIFIED", str(refs))
    return refs


def _cached_card() -> dict:
    return {
        "title": "T",
        "channel_id": "UC1",
        "channel_title": "Ch",
        "category_id": "27",
        "category": "Education",
        "role": "advisor",
        "description": "",
        "tags": [],
        "duration_sec": 0,
        "published_at": "",
        "links": {},
        "source": "cache",
    }


def test_enrichment_rewrite_does_not_drop_concurrent_append(isolated_refs, monkeypatch):
    # Realistic cached-card path: no network, enrichment stamps @meta on the row.
    monkeypatch.setattr(enrichment, "load_video_card", lambda base, vid: _cached_card())

    entered_rewrite = threading.Event()
    release_rewrite = threading.Event()
    real_format = references_format.format_data_line

    def pausing_format(row):
        # Runs between apply_row_updates' read and its commit, inside the lock.
        if not entered_rewrite.is_set():
            entered_rewrite.set()
            release_rewrite.wait(timeout=15)
        return real_format(row)

    monkeypatch.setattr(references_format, "format_data_line", pausing_format)

    other_line = (
        f"2026-07-08T01:13:00|[{OTHER_URL}]|(Other)|Ch|General\n"
    )

    errors: list[BaseException] = []

    def enrich():
        try:
            enrichment.enrich_youtube_reference(
                str(isolated_refs),
                VIDEO_URL,
                references_base=str(isolated_refs.parent),
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced by assertion below
            errors.append(exc)

    append_done = threading.Event()

    def do_append():
        try:
            ref_cli.append_to_file(str(isolated_refs), other_line)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            append_done.set()

    enrich_thread = threading.Thread(target=enrich)
    enrich_thread.start()

    try:
        # Wait until the rewrite has read the file and is paused before commit.
        assert entered_rewrite.wait(timeout=10)

        append_thread = threading.Thread(target=do_append)
        append_thread.start()

        # The append must NOT complete while the rewrite holds the archive lock.
        # (Before the shared lock, the append finished during this pause and was
        # then clobbered by the stale rewrite.)
        assert not append_done.wait(timeout=0.5)

        release_rewrite.set()
        enrich_thread.join(timeout=15)
        append_thread.join(timeout=15)
        assert not enrich_thread.is_alive()
        assert not append_thread.is_alive()
        assert errors == []
    finally:
        release_rewrite.set()
        enrich_thread.join(timeout=5)

    text = isolated_refs.read_text(encoding="utf-8")

    # Both rows survive exactly once (no dropped row, no duplicate).
    assert text.count(VIDEO_URL) == 1
    assert text.count(OTHER_URL) == 1
    # The enrichment stamp landed on the video row with correct metadata.
    assert "@meta" in text
    assert "Education" in text
    assert "advisor" in text
    assert "UC1" in text
