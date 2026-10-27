# local-transcribe queue integration (ref-cli)

**Audience:** ref-cli maintainers  
**Depends on:** [local-transcribe](https://github.com/draeician/local_transcribe) **≥ 0.7.0**
**Primary hook today:** `src/ref_cli/cli.py` → `add_url_to_pending_file()`  
**Status:** Implemented. This document specifies the complete contract, including **user-visible reporting when the source is already in the queue**.

---

## 1. Why this change is required

### Old model
When YouTube captions were unavailable / blocked, ref appended the URL to:

`~/references/transcripts/transcript-pending.md`

A human (or a separate `lt batch` run) later transcribed those URLs. That file is:

- Not multi-host safe
- Not deduplicated against in-flight work
- Invisible to the NFSv3 worker unless someone imports it (`lt queue import`)

### New model (local-transcribe 0.5.0+)
Transcription is **queue-first**:

| Role | Who | Responsibility |
|------|-----|----------------|
| **Producer** | ref-cli, `lt transcribe`, `lt batch`, other hosts | Enqueue only — never download/transcribe |
| **Worker** | One host with NLM lock (`lt worker`) | Download + Whisper + publish transcript JSON |
| **Storage** | Shared NFSv3 queue dir | Durable `pending` / `processing` / `completed` / `failed` / `retry` |

If ref keeps writing only to `transcript-pending.md`, new captures sit outside the worker loop and the operator backlog never drains through the queue.

### Ownership boundary
- **ref-cli** owns `references.md`, reconcile, enrichment, and user messaging.
- **local-transcribe** owns the queue, worker, downloads, and transcript JSON publish.
- local-transcribe **must never** rewrite `references.md`.
- Capture / enrich in ref **must not fail** solely because the queue or NFS is down — fall back to `transcript-pending.md`.

---

## 2. How ref-cli interacts with the queue

```text
ref capture / enrich
        │
        ▼
transcript already on disk? ──yes──► skip (existing behavior)
        │ no
        ▼
local_transcribe.queue_api.enqueue_youtube_safe(url, origin="ref", …)
        │
        ├─ success ──► EnqueueResult.kind (see §3) ──► report to user
        │
        └─ queue unavailable ──► append transcript-pending.md ──► report fallback
```

### Producer path (queue-first)

`ref` tries the durable queue in this order:

1. In-process `local_transcribe.queue_api.enqueue_youtube_safe(...)`.
2. An explicitly configured absolute `lt` executable, using
   `lt queue add ... --queue-dir ...`.
3. `lt` on `PATH` (legacy behavior).
4. `transcript-pending.md` as the final fallback.

When the durable queue succeeds, `ref` reports the queue kind and execution ID.
When only the pending file is updated, the status says so explicitly. `ref`
never reports a durable enqueue for a pending-file write.

### Producer configuration

Absolute paths are required for explicit configuration:

| Setting | Environment | Config key |
|---|---|---|
| Transcript mode | `REF_YOUTUBE_TRANSCRIPT_MODE` | `youtube_transcript_mode` |
| `lt` executable | `REF_LOCAL_TRANSCRIBE_LT` | `local_transcribe_lt` |
| Durable queue directory | `REF_LOCAL_TRANSCRIBE_QUEUE_DIR` | `local_transcribe_queue_dir` |
| Expected queue UUID (optional pin) | `REF_LOCAL_TRANSCRIBE_QUEUE_UUID` | `local_transcribe_queue_uuid` |

`REF_YOUTUBE_TRANSCRIPT_MODE` values:

- `remote_first` (default): preserve direct-caption retrieval, then queue on
  block/no-captions.
- `local_only`: never call `youtube-transcript-api`; reuse an existing
  transcript JSON or enqueue for local transcription. Cooldown markers are not
  read or modified in this mode.

Before invoking `lt`, `ref` verifies that the configured queue directory exists,
contains a parseable `queue.id`, and matches the optional expected UUID. Any
missing executable, identity mismatch, unavailable NFS path, CLI failure, or
unparseable output falls back to `transcript-pending.md` with a clear status.

Example service environment (`~/.config/ref/ref-api.env`):

```bash
REF_YOUTUBE_TRANSCRIPT_MODE=local_only
REF_LOCAL_TRANSCRIBE_LT=/home/draeician/.local/bin/lt
REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/opt/md2/music/youtube/transcripts/transcription-queue
REF_LOCAL_TRANSCRIBE_QUEUE_UUID=8c6fc098-8cbe-41ae-9689-dd759797a582
```

### API to call (preferred)

```python
from pathlib import Path
from local_transcribe.queue_api import enqueue_youtube_safe

PENDING = Path.home() / "references" / "transcripts" / "transcript-pending.md"

outcome = enqueue_youtube_safe(
    url,
    origin="ref",
    priority=20,                 # interactive / capture priority
    queue_dir=Path("/path/to/transcription-queue"),  # optional explicit queue
    pending_fallback=PENDING,
)
```

- Prefer **`enqueue_youtube_safe`** over bare `enqueue_youtube`.
- Bare `enqueue_youtube` raises on config/NFS errors; capture must not die for that.
- CLI equivalent for operators:
  `lt queue add "$URL" --origin ref --priority 20 --queue-dir /path/to/queue`.

---

## 3. Enqueue outcomes — **must report to the user**

`outcome.result` is an `EnqueueResult` with `.kind`, `.source_key`, `.execution`, `.message`, `.transcript_path`.

| `kind` | Meaning | User-facing message (recommended) |
|--------|---------|-----------------------------------|
| `enqueued` | New job created in `pending/` | `Queued for transcription (execution <id>). Worker will process it.` |
| `existing_active` | **Already in the queue** (`pending`, `processing`, or `retry`) | `Already in the transcription queue (<status>, execution <id>). No duplicate added.` |
| `already_completed` | Valid transcript already present (when checker used) | `Transcript already available at <path>.` |
| `requires_force` | Prior `failed`/`cancelled` blocks re-enqueue | `Previously failed/cancelled in queue; re-queue with force or \`lt queue retry --source youtube:<id>\`.` |
| *(fallback)* | `outcome.fell_back_to_pending` | `Queue unavailable (<error>); recorded in transcript-pending.md instead.` |

### Critical UX requirement
When `kind == "existing_active"`, ref **must tell the user the URL is already queued** — not silently return, and **not** claim it was newly added to `transcript-pending.md`.

Suggested helper:

```python
def format_queue_enqueue_message(outcome) -> str:
    if outcome.fell_back_to_pending:
        err = outcome.error or "queue unavailable"
        return (
            f"Transcript unavailable (queue offline: {err}; "
            f"recorded in transcript-pending.md)"
        )
    result = outcome.result
    if result is None:
        return "Transcript unavailable (queue enqueue failed)"

    ex = result.execution
    eid = ex.execution_id if ex else "?"
    status = ex.status if ex else "?"

    if result.kind == "enqueued":
        return (
            f"Transcript unavailable (queued for local-transcribe worker; "
            f"execution {eid})"
        )
    if result.kind == "existing_active":
        return (
            f"Transcript unavailable (already in transcription queue: "
            f"{status}, execution {eid})"
        )
    if result.kind == "already_completed":
        path = result.transcript_path or "on disk"
        return f"Transcript already completed ({path})"
    if result.kind == "requires_force":
        return (
            "Transcript unavailable (queue has a failed/cancelled job for this "
            "source; use lt queue retry or force re-enqueue)"
        )
    return f"Transcript unavailable (queue: {result.kind})"
```

Wire this into `format_transcript_failure()` / any path that currently hard-codes:

```text
Transcript unavailable (queued in transcript-pending.md)
```

That string is **wrong** once the durable queue is the primary path.

Also log at INFO with `kind`, `execution_id`, and `source_key` for operators.

---

## 4. What to change in ref-cli

### 4.1 `add_url_to_pending_file` (`src/ref_cli/cli.py`)

**Implemented behavior:**

1. If `video_id` and transcript JSON already on disk → skip (unchanged).
2. Resolve and verify explicit queue settings, then try
   `enqueue_youtube_safe(..., pending_fallback=TRANSCRIPT_PENDING_FILE)`.
3. If the package is unavailable, use an explicitly configured `lt` executable
   (or `lt` on `PATH`) with `--queue-dir`.
4. Return `PendingQueueResult` for every path so callers can show the exact
   outcome: enqueued, existing active, already completed, requires force,
   pending-file fallback, or pending-file failure.
5. Do not also append to `transcript-pending.md` when the durable queue
   succeeded.
6. Only use the pending file when the queue is unavailable or submission fails.
7. Never report a durable enqueue when the URL was only written to the pending
   file.

The stable result shape is:

```python
@dataclass
class PendingQueueResult:
    action: str  # enqueued | existing_active | already_completed | requires_force | pending_file | pending_file_failed | skipped_on_disk
    message: str
    execution_id: str | None = None
    source_key: str | None = None
```

### 4.2 User-visible strings

| Location | Change |
|----------|--------|
| `format_transcript_failure` | Use queue-aware wording from §3 |
| `enrichment.py` matchers for `'queued in transcript-pending'` | Also accept the new phrases (or a stable token like `queued for local-transcribe`) |
| `tests/test_transcript_blocking.py` / `test_enrichment.py` | Update expected strings; add cases for `existing_active` |

### 4.3 Packaging / runtime

The producer does **not** need `local_transcribe` installed in its own venv.
Configure an absolute `lt` path and queue directory instead:

```bash
REF_LOCAL_TRANSCRIBE_LT=/home/you/.local/bin/lt
REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/path/to/transcription-queue
REF_LOCAL_TRANSCRIBE_QUEUE_UUID=<queue-uuid>
```

`pipx inject ref-cli local-transcribe` remains optional for in-process API use,
but is not required for the supported CLI path. A missing executable, invalid
path, or identity mismatch falls back to `transcript-pending.md` with an
explicit message.

### 4.4 Optional: pre-check without enqueue

If you want a read-only “is it already queued?” before enqueue, you can shell out or call:

```bash
lt queue show-source youtube:VIDEO_ID
```

Enqueue itself already performs reservation / active-job checks and returns `existing_active`, so a separate pre-check is **optional**. Prefer trusting `EnqueueResult.kind` to avoid races.

### 4.5 Do **not**
- Start or stop the transcription worker from ref.
- Put cookie contents or YouTube API keys into queue job JSON (worker uses local `auth_profiles`).
- Treat YouTube Data API key as download auth — it is unrelated to yt-dlp / the worker.
- Rewrite queue files from ref except via the public `queue_api`.

---

## 4.6 Automatic reconciliation of completed executions

Once a queued execution completes, `ref-api` reconciles the corresponding
placeholder in `references.md`. The implementation lives in
`src/ref_cli/transcript_reconcile.py`; the API lifecycle starts/stops a
background worker in `src/ref_api/service.py`.

- Runs once at startup and then every
  `REF_TRANSCRIPT_RECONCILE_INTERVAL_SECONDS`
  (`transcript_reconcile_interval_seconds`, default **300 s**).
- Enabled by default; set `REF_TRANSCRIPT_RECONCILE_ENABLED=false`
  (`transcript_reconcile_enabled: false`) to disable.
- Recognizes durable-queue placeholders containing
  `queued for local-transcribe worker` or `already in transcription queue`
  plus an execution UUID.
- Looks up only that execution ID in the queue state directories (never scans
  historical completed jobs). It requires `status: completed`, matching
  `source_key`/`source` video, a valid execution generation, and a queue key
  record whose generation and `current_execution_id` identify the same
  execution. Missing or conflicting generation data is rejected.
- Reads `<paths.transcripts>/<video_id>.json`, **not** the worker-local
  `output_path` in older queue records. The JSON must have nonempty
  `transcript` text and `metadata.id == video_id`.
- Replaces only the placeholder field in `extra`; timestamp, URL, title,
  uploader, source, `@meta` fields, and other extras are preserved.
- Re-reads and revalidates target rows under the shared archive lock, writes a
  compressed backup before the first change in a pass, and makes no write when
  nothing changes.
- Queue state is read-only. Reconciliation never writes queue files, never
  re-enqueues, never calls YouTube, never downloads media, and never invokes
  Whisper. It does not touch `transcript-pending.md` or the legacy backlog.

The archive lock is process-local. Run reconciliation only in the single
`ref-api` host process that owns archive writes; a separate CLI process writing
the same archive is outside that lock (the existing single-writer convention).

## 5. Interaction summary (sequence)

```mermaid
sequenceDiagram
  participant User
  participant Ref as ref-cli
  participant API as local_transcribe.queue_api
  participant Q as NFSv3 queue
  participant W as lt worker

  User->>Ref: capture / enrich URL
  Ref->>Ref: transcript on disk?
  alt on disk
    Ref-->>User: use existing transcript
  else missing
    Ref->>API: enqueue_youtube_safe(url, origin=ref)
    alt enqueued
      API->>Q: write pending/*.json + reservation
      API-->>Ref: kind=enqueued
      Ref-->>User: Queued for worker (execution id)
      W->>Q: claim → processing → completed
    else already queued
      API-->>Ref: kind=existing_active
      Ref-->>User: Already in queue (status, execution id)
    else queue down
      API-->>Ref: fell_back_to_pending
      Ref-->>User: Recorded in transcript-pending.md
    end
  end
```

---

## 6. Acceptance checklist

- [x] `add_url_to_pending_file` uses `enqueue_youtube_safe` with pending fallback.
- [x] Explicit absolute `lt`/queue configuration works without importing `local_transcribe`.
- [x] Queue directory and optional expected UUID are verified before enqueue.
- [x] `local_only` never calls `youtube-transcript-api` and does not modify cooldown markers.
- [x] When source is already `pending`/`processing`/`retry`, user sees **“already in the transcription queue”** (with status + execution id when available).
- [x] New enqueue reports **queued for worker**, not “queued in transcript-pending.md”.
- [x] Fallback path still writes pending file and says so explicitly.
- [x] Enrichment / tests updated for new message strings.
- [ ] Manual smoke (requires deployment authorization):
  1. `ref` capture a URL with no captions → message shows enqueued + id.
  2. Capture the **same** URL again → message shows `existing_active` / already in queue.
  3. Stop NFS / break queue config → message shows pending-file fallback; capture still succeeds.
  4. `local_only` capture → no provider request; message shows local-only reason and queue/pending outcome.

---

## 7. References

| Doc | Location |
|-----|----------|
| Queue operator guide | `local_transcribe` → `docs/QUEUE_OPERATOR.md` |
| Short adapter contract | `local_transcribe` → `docs/REF_CLI_QUEUE_ADAPTER.md` |
| Public API | `local_transcribe` → `src/local_transcribe/queue_api.py` |
| Enqueue kinds | `local_transcribe` → `services/queue_store.py` (`EnqueueResult`) |
| Release | local-transcribe **v0.5.0** |

---

## 8. Minimal patch sketch

```python
# src/ref_cli/cli.py  (conceptual)

def add_url_to_pending_file(url: str, video_id: Optional[str] = None) -> PendingQueueResult:
    if video_id and transcript_exists_on_disk(video_id):
        return PendingQueueResult("skipped_on_disk", f"Transcript already on disk for {video_id}")

    try:
        from local_transcribe.queue_api import enqueue_youtube_safe
    except ImportError:
        _append_pending_file(url)
        return PendingQueueResult(
            "pending_file",
            "Transcript unavailable (local-transcribe not installed; recorded in transcript-pending.md)",
        )

    outcome = enqueue_youtube_safe(
        url,
        origin="ref",
        priority=20,
        pending_fallback=Path(TRANSCRIPT_PENDING_FILE),
    )
    msg = format_queue_enqueue_message(outcome)
    # logging.info(msg)
    action = (
        "pending_file"
        if outcome.fell_back_to_pending
        else (outcome.result.kind if outcome.result else "pending_file")
    )
    eid = (
        outcome.result.execution.execution_id
        if outcome.result and outcome.result.execution
        else None
    )
    return PendingQueueResult(action, msg, execution_id=eid,
                              source_key=(outcome.result.source_key if outcome.result else None))
```

Callers that build the reference row’s transcript placeholder should use `PendingQueueResult.message` instead of a hard-coded pending-file string.
