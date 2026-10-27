"""Tests for durable-queue placeholder reconciliation into references.md."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ref_cli import transcript_reconcile as tr
from ref_cli.references_format import HEADER_PREFIX, iter_data_rows

QUEUE_UUID = "11111111-2222-3333-4444-555555555555"
SMOKE_CASES = [
    ("jNQXAC9IVRw", "5d7be5b4-8401-4d4c-a9fd-77081c874b38"),
    ("0PT5c1z3LL8", "0e5878f4-af13-4b6d-a43e-2811ecf5be48"),
    ("RRBN_4L09Mg", "0b2f2e45-e793-485b-afd2-4d7d71d76f91"),
]
OTHER_EXECUTION_ID = "99999999-8888-7777-6666-555555555555"


@pytest.fixture(autouse=True)
def _clear_queue_env(monkeypatch):
    for name in (
        "REF_LOCAL_TRANSCRIBE_QUEUE_DIR",
        "REF_LOCAL_TRANSCRIBE_QUEUE_UUID",
        "REF_LOCAL_TRANSCRIBE_LT",
    ):
        monkeypatch.delenv(name, raising=False)


def _row(
    video_id: str,
    execution_id: str,
    *,
    extra: str | None = None,
    title: str = "Example Title",
    uploader: str = "Example Uploader",
    meta: str = "|@meta|Education|media|UCexample",
) -> str:
    if extra is None:
        extra = (
            "Transcript unavailable (local-only mode; queued for "
            f"local-transcribe worker; execution {execution_id})"
        )
    url = f"https://www.youtube.com/watch?v={video_id}"
    return (
        f"2026-10-27T00:42:08|[{url}]|({title})|{uploader}|YouTube|"
        f"{extra}{meta}"
    )


def _write_archive(path: Path, rows: list[str]) -> Path:
    path.write_text(
        f"{HEADER_PREFIX}2\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return path


def _write_transcript(
    directory: Path,
    video_id: str,
    *,
    text: str = "hello world",
    metadata_id: str | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{video_id}.json"
    path.write_text(
        json.dumps(
            {
                "transcript": text,
                "duration": 1,
                "comments": [],
                "metadata": {"id": metadata_id or video_id},
            }
        ),
        encoding="utf-8",
    )
    return path


def _make_queue(queue_dir: Path) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    (queue_dir / "queue.id").write_text(
        json.dumps({"queue_uuid": QUEUE_UUID}), encoding="utf-8"
    )
    return queue_dir


def _write_execution(
    queue_dir: Path,
    execution_id: str,
    video_id: str,
    *,
    state: str = "completed",
    **overrides,
) -> Path:
    _make_queue(queue_dir)
    state_dir = queue_dir / state
    state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "execution_id": execution_id,
        "source_key": f"youtube:{video_id}",
        "generation": 1,
        "source": f"https://www.youtube.com/watch?v={video_id}",
        "source_type": "youtube",
        "origin": "ref",
        "priority": 20,
        "status": "completed" if state == "completed" else state,
        "created_at": "2026-10-27T00:42:07+00:00",
        "updated_at": "2026-10-27T00:42:17+00:00",
        "available_at": "2026-10-27T00:42:07+00:00",
        "started_at": "2026-10-27T00:42:13+00:00",
        "completed_at": "2026-10-27T00:42:17+00:00",
        "attempts": 1,
        "max_attempts": 3,
        "worker": None,
        "required_host": None,
        # Deliberately worker-local: reconciliation must not use this path.
        "output_path": f"/home/aether/references/transcripts/{video_id}.json",
        "error": None,
        "options": {},
    }
    record.update(overrides)
    path = state_dir / f"{execution_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _write_key(
    queue_dir: Path,
    video_id: str,
    execution_id: str,
    *,
    generation: int = 1,
    **overrides,
) -> Path:
    _make_queue(queue_dir)
    keys = queue_dir / "keys"
    keys.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "source_key": f"youtube:{video_id}",
        "source_type": "youtube",
        "current_execution_id": execution_id,
        "generation": generation,
        "created_at": "2026-10-27T00:42:08+00:00",
        "updated_at": "2026-10-27T00:42:08+00:00",
    }
    record.update(overrides)
    path = keys / f"youtube__{video_id}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _setup_success(tmp_path: Path, video_id: str, execution_id: str):
    archive = _write_archive(tmp_path / "references.md", [_row(video_id, execution_id)])
    transcripts = tmp_path / "transcripts"
    transcript = _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)
    return archive, transcripts, queue_dir, transcript


def _reconcile(archive: Path, transcripts: Path, queue_dir: Path, **kwargs):
    return tr.reconcile_transcripts(
        archive_path=str(archive),
        transcripts_dir=str(transcripts),
        queue_dir=str(queue_dir),
        config={},
        **kwargs,
    )


def _only_row(path: Path):
    rows = list(iter_data_rows(str(path)))
    assert len(rows) == 1
    return rows[0]


@pytest.mark.parametrize("video_id,execution_id", SMOKE_CASES)
def test_successful_completed_job_reconciliation(
    tmp_path, video_id, execution_id
):
    archive, transcripts, queue_dir, transcript = _setup_success(
        tmp_path, video_id, execution_id
    )
    before = _only_row(archive)

    result = _reconcile(archive, transcripts, queue_dir)

    after = _only_row(archive)
    assert result.updated == 1
    assert result.errors == 0
    assert after.extra == str(transcript)
    assert after.timestamp == before.timestamp
    assert after.url == before.url
    assert after.title == before.title
    assert after.uploader == before.uploader
    assert after.source == before.source
    assert after.category == before.category
    assert after.role == before.role
    assert after.channel_id == before.channel_id
    assert list(tmp_path.glob("references.md.bak-*"))
    assert result.backup_path


def test_already_in_transcription_queue_placeholder_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    extra = (
        "Transcript unavailable (already in transcription queue: completed, "
        f"execution {execution_id})"
    )
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id, extra=extra)
    ])
    transcripts = tmp_path / "transcripts"
    transcript = _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 1
    assert _only_row(archive).extra == str(transcript)


def test_placeholder_preserves_other_extra_fields(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    extra = (
        "Transcript unavailable (queued for local-transcribe worker; "
        f"execution {execution_id})|legacy-extra"
    )
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id, extra=extra)
    ])
    transcripts = tmp_path / "transcripts"
    transcript = _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    assert _reconcile(archive, transcripts, queue_dir).updated == 1
    assert _only_row(archive).extra == f"{transcript}|legacy-extra"


@pytest.mark.parametrize("state", ["pending", "processing", "retry"])
def test_incomplete_or_pending_jobs_not_reconciled(tmp_path, state):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id, state=state)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.skipped == 1
    assert "Transcript unavailable" in _only_row(archive).extra


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_failed_and_cancelled_jobs_not_reconciled(tmp_path, state):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id, state=state)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.skipped == 1
    assert f"execution is {state}" in " ".join(result.reasons)


def test_missing_transcript_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "transcript file missing" in " ".join(result.reasons)
    assert "Transcript unavailable" in _only_row(archive).extra


def test_malformed_transcript_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / f"{video_id}.json").write_text("{not json", encoding="utf-8")
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "malformed transcript" in " ".join(result.reasons)


def test_empty_transcript_text_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id, text="   ")
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "transcript text is empty" in " ".join(result.reasons)


def test_transcript_metadata_video_mismatch_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id, metadata_id=SMOKE_CASES[1][0])
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "video ID does not match" in " ".join(result.reasons)


def test_execution_belongs_to_different_video_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    other_video_id = SMOKE_CASES[1][0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(
        queue_dir,
        execution_id,
        other_video_id,
        source_key=f"youtube:{other_video_id}",
    )
    _write_key(queue_dir, other_video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "different video" in " ".join(result.reasons)


def test_execution_id_mismatch_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    record_path = _write_execution(queue_dir, execution_id, video_id)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["execution_id"] = OTHER_EXECUTION_ID
    record_path.write_text(json.dumps(record), encoding="utf-8")
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "does not match queue filename" in " ".join(result.reasons)


def test_execution_not_found_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "execution not found" in " ".join(result.reasons)


def test_missing_execution_generation_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    record_path = _write_execution(queue_dir, execution_id, video_id)
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.pop("generation")
    record_path.write_text(json.dumps(record), encoding="utf-8")
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "execution generation" in " ".join(result.reasons)


def test_missing_key_generation_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    key_path = _write_key(queue_dir, video_id, execution_id)
    key = json.loads(key_path.read_text(encoding="utf-8"))
    key.pop("generation")
    key_path.write_text(json.dumps(key), encoding="utf-8")

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "key generation" in " ".join(result.reasons)


def test_conflicting_generation_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id, generation=2)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "generation conflict" in " ".join(result.reasons)


def test_stale_current_generation_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(
        queue_dir,
        video_id,
        execution_id,
        current_execution_id=OTHER_EXECUTION_ID,
    )

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "not the current queue generation" in " ".join(result.reasons)


def test_missing_queue_key_not_reconciled(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "queue key record missing" in " ".join(result.reasons)


def test_queued_row_with_enrichment_metadata_preserved(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(
            video_id,
            execution_id,
            meta="|@meta|Film & Animation|advisor|UC4QobU6STFB0P71PMvOGN5A",
        )
    ])
    transcripts = tmp_path / "transcripts"
    transcript = _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    assert _reconcile(archive, transcripts, queue_dir).updated == 1
    row = _only_row(archive)
    assert row.extra == str(transcript)
    assert row.category == "Film & Animation"
    assert row.role == "advisor"
    assert row.channel_id == "UC4QobU6STFB0P71PMvOGN5A"


def test_concurrent_archive_append_is_preserved(tmp_path, monkeypatch):
    video_id, execution_id = SMOKE_CASES[0]
    appended_url = "https://example.org/concurrent"
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    original_scan = tr._scan_candidates

    def scan_then_append(path):
        candidates = original_scan(path)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                f"2026-10-27T00:43:00|[{appended_url}]|(Concurrent)|Other|General\n"
            )
        return candidates

    monkeypatch.setattr(tr, "_scan_candidates", scan_then_append)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 1
    text = archive.read_text(encoding="utf-8")
    assert appended_url in text
    assert "Transcript unavailable" not in text


def test_concurrent_enrichment_update_is_preserved(tmp_path, monkeypatch):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    original_scan = tr._scan_candidates

    def scan_then_enrich(path):
        candidates = original_scan(path)
        text = Path(path).read_text(encoding="utf-8")
        text = text.replace("(Example Title)|Example Uploader", "(New Title)|New Uploader")
        text = text.replace(
            "|@meta|Education|media|UCexample",
            "|@meta|Science & Technology|advisor|UCnew",
        )
        Path(path).write_text(text, encoding="utf-8")
        return candidates

    monkeypatch.setattr(tr, "_scan_candidates", scan_then_enrich)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 1
    row = _only_row(archive)
    assert row.title == "New Title"
    assert row.uploader == "New Uploader"
    assert row.category == "Science & Technology"
    assert row.role == "advisor"
    assert row.channel_id == "UCnew"
    assert row.extra.endswith(f"{video_id}.json")


def test_repeated_reconciliation_is_idempotent(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive, transcripts, queue_dir, _ = _setup_success(
        tmp_path, video_id, execution_id
    )

    first = _reconcile(archive, transcripts, queue_dir)
    backups_after_first = list(tmp_path.glob("references.md.bak-*"))
    text_after_first = archive.read_text(encoding="utf-8")

    second = _reconcile(archive, transcripts, queue_dir)

    assert first.updated == 1
    assert second.updated == 0
    assert second.candidates == 0
    assert archive.read_text(encoding="utf-8") == text_after_first
    assert list(tmp_path.glob("references.md.bak-*")) == backups_after_first


def test_queue_unavailable_no_changes(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)

    result = _reconcile(archive, transcripts, tmp_path / "missing-queue")

    assert result.updated == 0
    assert "queue unavailable" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_missing_transcripts_directory_no_changes(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    original = archive.read_text(encoding="utf-8")
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, tmp_path / "missing-transcripts", queue_dir)

    assert result.updated == 0
    assert "transcript file missing" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_malformed_queue_record_no_changes(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    completed = queue_dir / "completed"
    completed.mkdir()
    (completed / f"{execution_id}.json").write_text("{broken", encoding="utf-8")

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "malformed completed execution record" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_incomplete_queue_record_no_changes(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id, status="processing")

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert "not completed" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_queue_identity_mismatch_no_changes(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id)
    ])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = tr.reconcile_transcripts(
        archive_path=str(archive),
        transcripts_dir=str(transcripts),
        queue_dir=str(queue_dir),
        config={"local_transcribe_queue_uuid": "different-uuid"},
    )

    assert result.updated == 0
    assert "queue unavailable" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_multiple_execution_ids_are_skipped(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    extra = (
        "Transcript unavailable (queued for local-transcribe worker; "
        f"execution {execution_id}; execution {OTHER_EXECUTION_ID})"
    )
    archive = _write_archive(tmp_path / "references.md", [
        _row(video_id, execution_id, extra=extra)
    ])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.candidates == 0
    assert archive.read_text(encoding="utf-8") == original


def test_non_youtube_placeholder_is_ignored(tmp_path):
    video_id, execution_id = SMOKE_CASES[0]
    row = _row(video_id, execution_id).replace("|YouTube|", "|General|")
    archive = _write_archive(tmp_path / "references.md", [row])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")
    _write_execution(queue_dir, execution_id, video_id)
    _write_key(queue_dir, video_id, execution_id)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.candidates == 0
    assert archive.read_text(encoding="utf-8") == original


def test_valid_transcript_rows_are_untouched(tmp_path):
    video_id = SMOKE_CASES[0][0]
    valid_path = tmp_path / "transcripts" / f"{video_id}.json"
    valid_row = _row(
        video_id,
        SMOKE_CASES[0][1],
        extra=str(valid_path),
        meta="",
    )
    failure_row = (
        "2026-10-27T00:43:00|[https://example.org/x]|(Failure)|Other|General|"
        "No transcript available"
    )
    archive = _write_archive(tmp_path / "references.md", [valid_row, failure_row])
    original = archive.read_text(encoding="utf-8")
    transcripts = tmp_path / "transcripts"
    _write_transcript(transcripts, video_id)
    queue_dir = _make_queue(tmp_path / "queue")

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.candidates == 0
    assert archive.read_text(encoding="utf-8") == original


def test_backup_failure_aborts_rewrite(tmp_path, monkeypatch):
    video_id, execution_id = SMOKE_CASES[0]
    archive, transcripts, queue_dir, _ = _setup_success(
        tmp_path, video_id, execution_id
    )
    original = archive.read_text(encoding="utf-8")

    def fail_backup(*args, **kwargs):
        raise OSError("NFS unavailable")

    monkeypatch.setattr(tr, "backup_file", fail_backup)

    result = _reconcile(archive, transcripts, queue_dir)

    assert result.updated == 0
    assert result.errors == 1
    assert "backup failed" in " ".join(result.reasons)
    assert archive.read_text(encoding="utf-8") == original


def test_missing_archive_is_skipped(tmp_path):
    result = tr.reconcile_transcripts(
        archive_path=str(tmp_path / "missing.md"),
        transcripts_dir=str(tmp_path / "transcripts"),
        queue_dir=str(tmp_path / "queue"),
        config={},
    )
    assert result.updated == 0
    assert "archive not found" in " ".join(result.reasons)


def test_settings_defaults_and_invalid_values(monkeypatch, caplog):
    monkeypatch.delenv(tr.ENV_ENABLED, raising=False)
    monkeypatch.delenv(tr.ENV_INTERVAL_SECONDS, raising=False)
    assert tr.resolve_enabled({}) is True
    assert tr.resolve_interval_seconds({}) == tr.DEFAULT_INTERVAL_SECONDS

    monkeypatch.setenv(tr.ENV_ENABLED, "off")
    assert tr.resolve_enabled({}) is False

    monkeypatch.setenv(tr.ENV_ENABLED, "maybe")
    with caplog.at_level("WARNING", logger=tr.__name__):
        assert tr.resolve_enabled({}) is True
    assert any("Ignoring invalid" in record.message for record in caplog.records)

    for bad in ("nope", "0", "-1", "nan", "inf"):
        monkeypatch.setenv(tr.ENV_INTERVAL_SECONDS, bad)
        assert tr.resolve_interval_seconds({}) == tr.DEFAULT_INTERVAL_SECONDS

    monkeypatch.setenv(tr.ENV_INTERVAL_SECONDS, "42.5")
    assert tr.resolve_interval_seconds({}) == 42.5
