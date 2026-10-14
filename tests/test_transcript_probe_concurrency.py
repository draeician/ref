"""Deterministic regression tests for cross-process recovery-probe ownership.

These tests target the QA-failed races on the reviewed implementation
(``d2b2a028253cbc09dd2dc94b28696ee139b3eafb``):

1. after cooldown expiry, more than one thread/process could pass the old
   process-local ``probe_guard`` and contact the provider (no ownership was held
   across the provider call);
2. an older in-flight success unconditionally erased a newer cooldown;
3. malformed marker metadata could raise and poison capture.

The threaded and (real) multi-process tests below exercise only the public CLI
surface (``cli.fetch_youtube_transcript`` + ``enter_block``) so they fail against
the reviewed SHA (two provider calls) and pass after the correction (one).
"""

import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ref_cli import cli, transcript_block

VIDEO_A = "aaaaaaaaaaa"
VIDEO_B = "bbbbbbbbbbb"
T0 = 1_700_000_000.0
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

FAKE_TRANSCRIPT = {
    "transcript": "hello",
    "duration": 1,
    "comments": [],
    "metadata": {"id": "?", "title": "T", "channel": "C", "published_at": "D"},
}


@pytest.fixture(autouse=True)
def _clean_memory_state():
    for attr in ("_memory_state", "_memory_authoritative"):
        obj = getattr(transcript_block, attr, None)
        if obj is not None:
            try:
                obj.clear()
            except Exception:  # pragma: no cover - defensive
                pass
    yield
    for attr in ("_memory_state", "_memory_authoritative"):
        obj = getattr(transcript_block, attr, None)
        if obj is not None:
            try:
                obj.clear()
            except Exception:  # pragma: no cover - defensive
                pass


def _expired_marker(transcripts_dir, *, blocked_until=time.time() - 100):
    transcript_block.enter_block(str(transcripts_dir), duration_seconds=60, now=blocked_until)
    assert transcript_block.is_blocked(str(transcripts_dir), now=time.time()) is False


# ---------------------------------------------------------------------------
# Threaded single flight
# ---------------------------------------------------------------------------


def test_threaded_recovery_probe_is_single_flight(monkeypatch, tmp_path):
    """Two threads entering an expired cooldown together: exactly one provider
    call; the other video is skipped and routed to queue/fallback (blocked)."""
    transcripts = str(tmp_path / "transcripts")
    monkeypatch.setattr(cli, "TRANSCRIPTS_DIR", transcripts)
    _expired_marker(transcripts)

    provider_calls = []
    calls_lock = threading.Lock()
    first_probe = threading.Event()
    release_first = threading.Event()

    def fake_provider(video_id, save_to_file=False):
        with calls_lock:
            provider_calls.append(video_id)
            count = len(provider_calls)
        first_probe.set()
        if count == 1:
            release_first.wait(timeout=15)
        return dict(FAKE_TRANSCRIPT, metadata={"id": video_id, "title": "T",
                                               "channel": "C", "published_at": "D"})

    monkeypatch.setattr(cli, "get_youtube_transcript_with_metadata", fake_provider)

    results = {}
    results_lock = threading.Lock()

    def worker(video_id):
        transcript_file, failure_info = cli.fetch_youtube_transcript(video_id)
        with results_lock:
            results[video_id] = (transcript_file, failure_info)

    t1 = threading.Thread(target=worker, args=(VIDEO_A,))
    t2 = threading.Thread(target=worker, args=(VIDEO_B,))
    t1.start()
    assert first_probe.wait(timeout=15), "first probe did not start"
    # Hold the first provider fetch in flight while the second thread runs.
    t2.start()
    time.sleep(0.5)
    release_first.set()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert not t1.is_alive() and not t2.is_alive()
    assert len(provider_calls) == 1, (
        f"expected exactly one provider call, got {len(provider_calls)}"
    )
    blocked = [
        video_id
        for video_id, (tf, fi) in results.items()
        if tf is None and fi is not None and fi[0] == "blocked"
    ]
    assert len(blocked) == 1, f"exactly one video should be skipped->queued: {results}"


# ---------------------------------------------------------------------------
# Real multi-process single flight (not merely simulated by threads)
# ---------------------------------------------------------------------------

_WORKER = textwrap.dedent("""
    import os
    import sys
    import time

    sys.path.insert(0, {src!r})
    sys.path.insert(0, {root!r})

    from ref_cli import cli, transcript_block

    transcripts, go_file, attempts_file, video_id = sys.argv[1:5]

    cli.TRANSCRIPTS_DIR = transcripts

    class _NoProvider:
        def fetch(self, *a, **k):
            raise RuntimeError("legacy provider must not be reached")
        def list(self, *a, **k):
            raise RuntimeError("legacy provider must not be reached")

    cli.YouTubeTranscriptApi = _NoProvider

    def fake_provider(video_id_arg, save_to_file=False):
        # Record that THIS process contacted the provider, then hold long enough
        # for a sibling process to interleave its own probe attempt.
        with open(attempts_file, "a", encoding="utf-8") as handle:
            handle.write(video_id_arg + "\\n")
            handle.flush()
        time.sleep(3.0)
        return {{
            "transcript": "hello",
            "duration": 1,
            "comments": [],
            "metadata": {{
                "id": video_id_arg, "title": "T", "channel": "C", "published_at": "D",
            }},
        }}

    cli.get_youtube_transcript_with_metadata = fake_provider

    deadline = time.time() + 10
    while not os.path.exists(go_file):
        if time.time() > deadline:
            sys.exit(3)
        time.sleep(0.005)

    cli.fetch_youtube_transcript(video_id)
    sys.exit(0)
""")


def test_multi_process_recovery_probe_is_single_flight(tmp_path):
    """Two independent OS processes on the same transcripts dir after an expired
    marker: precisely one recovery probe claims ownership; the other skips."""
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    go_file = tmp_path / "go"
    attempts_file = tmp_path / "attempts.txt"
    _expired_marker(str(transcripts))

    worker = tmp_path / "probe_worker.py"
    worker.write_text(
        _WORKER.format(src=str(SRC), root=str(ROOT)), encoding="utf-8"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(ROOT)])

    p1 = subprocess.Popen(
        [sys.executable, str(worker), str(transcripts), str(go_file), str(attempts_file), VIDEO_A],
        env=env,
    )
    p2 = subprocess.Popen(
        [sys.executable, str(worker), str(transcripts), str(go_file), str(attempts_file), VIDEO_B],
        env=env,
    )
    time.sleep(0.7)  # let both processes get ready and wait on the go file
    go_file.write_text("go", encoding="utf-8")
    rc1 = p1.wait(timeout=60)
    rc2 = p2.wait(timeout=60)

    assert rc1 == 0, f"worker A exited {rc1}"
    assert rc2 == 0, f"worker B exited {rc2}"
    calls = attempts_file.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1, (
        f"expected exactly one provider call across two OS processes, got {len(calls)}"
    )


# ---------------------------------------------------------------------------
# Stale success / epoch protection
# ---------------------------------------------------------------------------


def test_stale_probe_success_cannot_clear_newer_block(tmp_path):
    """A pre-ban provider success finishing after a newer block was recorded must
    not erase that newer cooldown."""
    d = str(tmp_path)
    transcript_block.enter_block(d, duration_seconds=60, now=T0 - 100)
    # A claims the expired recovery probe.
    decision = transcript_block.begin_probe(d, now=T0)
    assert decision.allowed and decision.probing

    # B (another process) records a fresh block while A is still in flight.
    transcript_block.enter_block(d, duration_seconds=600, now=T0 + 10)

    # A finishes successfully (stale) -> must NOT clear B's block.
    transcript_block.finish_probe(d, decision, transcript_file="x.json", now=T0 + 20)

    assert transcript_block.is_blocked(d, now=T0 + 30) is True
    assert transcript_block.blocked_until(d, now=T0 + 30) == T0 + 610


def test_stale_probe_cannot_overwrite_current_epoch_after_renewal(tmp_path):
    """A stale probe's success must not remove the marker or refresh it to the
    old (expired) epoch after a renewal happened behind its back."""
    d = str(tmp_path)
    transcript_block.enter_block(d, duration_seconds=60, now=T0 - 100)
    decision = transcript_block.begin_probe(d, now=T0)
    # Different owner's blocked outcome renews the cooldown.
    transcript_block.enter_block(d, duration_seconds=600, now=T0 + 10)
    # A's stale success:
    transcript_block.finish_probe(d, decision, transcript_file="x.json", now=T0 + 25)
    marker = transcript_block.read_marker(d)
    assert marker is not None
    assert marker["blocked_until"] == T0 + 610


def test_renewed_block_takes_precedence_over_in_flight_success(tmp_path):
    """If a confirmed block is returned by our own probe, it must renew the
    cooldown even though the marker was already active behind us (no extension,
    but never cleared)."""
    d = str(tmp_path)
    transcript_block.enter_block(d, duration_seconds=60, now=T0 - 100)
    decision = transcript_block.begin_probe(d, now=T0)
    # Someone renewed the cooldown while our probe was in flight.
    transcript_block.enter_block(d, duration_seconds=600, now=T0 + 10)
    # Our probe also got blocked -> cooldown stays, is NOT extended further by us.
    transcript_block.finish_probe(
        d, decision, failure_info=("blocked", "still blocked"), now=T0 + 30
    )
    assert transcript_block.is_blocked(d, now=T0 + 40) is True
    assert transcript_block.blocked_until(d, now=T0 + 40) == T0 + 610


# ---------------------------------------------------------------------------
# Lease bounds / crash recovery / backoff
# ---------------------------------------------------------------------------


def test_crashed_probe_owner_lease_expires(tmp_path):
    """A probe owner that dies without finishing cannot wedge ingestion: the
    lease is bounded, and a later caller reclaims it."""
    d = str(tmp_path)
    transcript_block.enter_block(d, duration_seconds=60, now=T0 - 100)
    decision = transcript_block.begin_probe(d, now=T0)
    assert decision.allowed and decision.probing
    # Lease is active for another process.
    blocked = transcript_block.begin_probe(d, now=T0 + 1)
    assert blocked.allowed is False
    # Owner "crashed"; after PROBE_LEASE_SECONDS a new owner may claim.
    recovered = transcript_block.begin_probe(
        d, now=T0 + transcript_block.PROBE_LEASE_SECONDS + 1
    )
    assert recovered.allowed is True
    assert recovered.probing is True


def test_unrelated_probe_failure_arms_backoff_then_recovers(tmp_path):
    """A failed (non-block) probe releases the lease and arms a bounded backoff;
    recovery eventually happens without a probe stampede."""
    d = str(tmp_path)
    transcript_block.enter_block(d, duration_seconds=60, now=T0 - 100)
    decision = transcript_block.begin_probe(d, now=T0)
    transcript_block.finish_probe(
        d, decision, failure_info=("enhanced", "network hiccup"), now=T0 + 1
    )
    # Backoff active -> next caller is skipped (single flight, no stampede).
    skipped = transcript_block.begin_probe(d, now=T0 + 2)
    assert skipped.allowed is False
    assert "probe" in skipped.message.lower()
    # After the backoff window a fresh single probe is allowed.
    later = transcript_block.begin_probe(
        d, now=T0 + 2 + transcript_block.PROBE_BACKOFF_SECONDS + 1
    )
    assert later.allowed is True
    assert later.probing is True


# ---------------------------------------------------------------------------
# Hardened marker parsing
# ---------------------------------------------------------------------------

MALFORMED_MARKERS = [
    '{"blocked_until": 1700000100, "set_at": "garbage", "duration_seconds": "abc"}',
    '{"blocked_until": 1700000100, "set_at": [1, 2], "duration_seconds": []}',
    '{"blocked_until": 1700000100, "set_at": null, "duration_seconds": null}',
    '{"blocked_until": NaN}',
    '{"blocked_until": 1e999}',
    '{"blocked_until": -5}',
    '{"blocked_until": "abc"}',
    '{"blocked_until": 1700000100, "duration_seconds": 1e999}',
    '{"blocked_until": 1700000100, "lease_expires_at": "nope", "next_probe_at": {}}',
    '[]',
    '"just a string"',
]


@pytest.mark.parametrize("content", MALFORMED_MARKERS)
def test_malformed_marker_never_throws(tmp_path, content, caplog):
    """Malformed marker JSON/numeric fields must not throw, must not poison queue
    capture, and must not wedge a probe decision."""
    d = str(tmp_path)
    Path(transcript_block.marker_path(d)).write_text(content, encoding="utf-8")
    assert transcript_block.is_blocked(d, now=T0) in (True, False)
    decision = transcript_block.begin_probe(d, now=T0)
    assert isinstance(decision.allowed, bool)


def test_implausible_marker_timestamp_ignored(tmp_path, caplog):
    """An effectively-forever blocked_until (beyond the plausibility bound) is
    treated as malformed instead of wedging capture forever."""
    d = str(tmp_path)
    Path(transcript_block.marker_path(d)).write_text(
        '{"blocked_until": 5000000000}', encoding="utf-8"
    )
    assert transcript_block.is_blocked(d, now=time.time()) is False
    assert transcript_block.begin_probe(d, now=time.time()).allowed is True
