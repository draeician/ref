# HANDOFF — YouTube transcript routing investigation

**Date:** 2026-10-27 (UTC)
**Mode:** PR #22 deployed to production with verification. One manual smoke capture was submitted; no backlog import or worker configuration change was made.
**Repository:** https://github.com/draeician/ref  
**Scope:** why recent YouTube ingests are routed to local-transcribe/Whisper instead of using captions directly, and the production rollout of the durable queue fallback.

## Executive diagnosis

**Primary cause (confirmed): YouTube is blocking direct caption retrieval from `minion-26`.** A controlled single-video test at **2026-10-26T18:13:09Z** returned `youtube_transcript_api._errors.IpBlocked` after 1.257s. `IpBlocked` is a subclass of `RequestBlocked` and represents an IP-level block; this library raises it for HTTP 429 or a reCAPTCHA challenge page. The numeric status was not exposed. The block began by **2026-10-26T00:38:09Z** and was still active at 18:13Z. The cooldown then suppressed every subsequent transcript provider call for one hour; each recovery probe was blocked again, so the cycle repeated at 05:46, 11:30, 12:31, and 14:37 UTC.

**Secondary cause (high confidence): the local-transcribe queue is not reachable from the running service.** The service virtualenv does not contain `local_transcribe`, and the systemd service `PATH` does not contain `lt`; `lt` also has no configured queue path on this host. Every failure therefore takes the final fallback: append to `transcript-pending.md`. No new local-transcribe/Whisper queue job has been created since **2026-10-24T21:03:29Z**, and none of the recent sample video IDs appear in the queue. The corrective implementation adds explicit absolute `lt`/queue configuration, queue identity verification, and a `local_only` mode so the producer does not need `local_transcribe` installed in its own venv. **Deployed to production on 2026-10-27.**

**Latent defect (high confidence): the enhanced `get_transcript.py` handler is not packaged and cannot be imported in production.** `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the running service. The legacy provider path still worked until the IP block, so this is not the trigger, but it removes the enhanced path and contributes to poor diagnostics.

**Diagnostics gap (high confidence): production logs hide the provider exception.** The controlled test identified `IpBlocked`, but the running service logs only the generic cooldown warning; it does not record the exception class/message. The test also confirmed that the exception object does not expose a numeric HTTP status.

## Phase 3 — automatic transcript reconciliation (implemented, not deployed)

**Status:** Implemented and tested on a feature branch; **no production deployment,
service restart, or live archive modification was performed under this task.**

The storage-related findings below are **superseded** by the verified migration:
Aether now has a symlink from `~/references/transcripts` to
`/opt/md2/music/youtube/transcripts`, and the 542 missing `.generations` files
were copied with SHA-256 verification and zero conflicts. `minion-26` can read
all three smoke-test transcript JSON files. The remaining work was stale queued
placeholders in `references.md`.

### Implementation

- Core reconciler: `src/ref_cli/transcript_reconcile.py`.
- API lifecycle: startup pass plus periodic pass in `src/ref_api/service.py`;
  started/stopped by the FastAPI lifespan in `src/ref_api/app.py`.
- Only rows containing `queued for local-transcribe worker` or
  `already in transcription queue` with an execution UUID are considered.
- Only the referenced execution ID is loaded from the queue state directories;
  historical completed jobs are never enumerated.
- Requires `status: completed`, matching execution `source_key`/`source` video,
  a valid execution generation, and a matching queue key record whose generation
  and `current_execution_id` identify that execution. Missing or conflicting
  generation data is rejected.
- Reads the configured shared `paths.transcripts/<video_id>.json`, never the
  worker-local `output_path`; requires nonempty transcript text and
  `metadata.id == video_id`.
- Replaces only the placeholder field in `extra`, preserving timestamp, URL,
  title, uploader, source, `@meta`, and other extra fields.
- Re-reads/revalidates target rows under the shared archive lock and writes a
  compressed backup before the first change in a pass. Repeated passes are
  idempotent and write nothing when no row changes.
- Queue files are read-only; no re-enqueue, YouTube call, media download, or
  Whisper invocation occurs. `transcript-pending.md` and the 792-URL legacy
  backlog are untouched.

### Configuration

| Setting | Environment | Config key | Default |
|---|---|---|---|
| Enable reconciler | `REF_TRANSCRIPT_RECONCILE_ENABLED` | `transcript_reconcile_enabled` | `true` |
| Interval (seconds) | `REF_TRANSCRIPT_RECONCILE_INTERVAL_SECONDS` | `transcript_reconcile_interval_seconds` | `300` |

The reconciler is a no-op when no durable queue directory is configured. It uses
the existing `REF_LOCAL_TRANSCRIBE_QUEUE_DIR` / `REF_LOCAL_TRANSCRIBE_QUEUE_UUID`
settings and `paths.transcripts`.

### Smoke-test acceptance cases

On the first pass after deployment, these existing completed executions should
replace their placeholders with the corresponding shared transcript JSON paths,
without re-transcription:

| Video ID | Execution ID | Expected transcript |
|---|---|---|
| `jNQXAC9IVRw` | `5d7be5b4-8401-4d4c-a9fd-77081c874b38` | `<paths.transcripts>/jNQXAC9IVRw.json` |
| `0PT5c1z3LL8` | `0e5878f4-af13-4b6d-a43e-2811ecf5be48` | `<paths.transcripts>/0PT5c1z3LL8.json` |
| `RRBN_4L09Mg` | `0b2f2e45-e793-485b-afd2-4d7d71d76f91` | `<paths.transcripts>/RRBN_4L09Mg.json` |

### Deployment and rollback (future, separately authorized)

1. Merge and install the package on `minion-26`; keep the queue settings already
   in `~/.config/ref/ref-api.env`. Optionally add the reconciliation settings.
2. Restart `ref-api.service` in an idle window. Verify `/health` and journal
   lines showing the reconciler started, then confirm only the three placeholder
   rows changed and a `.bak-<timestamp>.gz` backup exists.
3. To roll back behavior without downgrading: set
   `REF_TRANSCRIPT_RECONCILE_ENABLED=false` and restart. To roll back code,
   restore the prior wheel/source revision and restart. Do not restore an archive
   snapshot over newer captures; use the generated backup only if the rewritten
   rows need manual recovery.

Cross-process limitation: the archive lock is process-local. Reconciliation
must run only in the single `ref-api` writer process; a separate CLI process
writing the same archive is outside that lock (pre-existing single-writer model).

## Controlled live test — 2026-10-26T18:13:09Z

Authorized test: exactly one `YouTubeTranscriptApi().fetch("rRtN1pN6KQw")` invocation with zero retries, using the production interpreter and the library directly (not `ref` and not the `/urls` endpoint). No proxy configuration was supplied, so the library's internal retry path was disabled.

| Field | Result |
|---|---|
| Timestamp | Started **2026-10-26T18:13:09Z**; finished **2026-10-26T18:13:11Z** |
| Outcome | **Failure** |
| Exception class | **`IpBlocked`** |
| Exception module | `youtube_transcript_api._errors` |
| Exception MRO | `IpBlocked` → `RequestBlocked` → `CouldNotRetrieveTranscript` → `YouTubeTranscriptApiException` → `Exception` |
| Sanitized message | `Could not retrieve a transcript for the video <url> This is most likely caused by: | YouTube is blocking requests from your IP. This usually is due to one of the following reasons:` |
| Sanitized cause | `YouTube is blocking requests from your IP. This usually is due to one of the following reasons: | - You have done too many requests and your IP has been blocked by YouTube` |
| HTTP status | **Not exposed** (`null` on the exception object). This library raises `IpBlocked` for HTTP 429 or a reCAPTCHA challenge page; the invocation did not expose which condition occurred. |
| Caption segments | Not applicable (failure) |
| Elapsed time | **1.257 s** |
| Preflight | Marker expired (`blocked_until` = 2026-10-26T15:37:13Z), `lease_expires_at` = 0.0, `lease_owner` = null, `next_probe_at` = 0.0; no active transcript/provider probe process; no recent transcript/cooldown journal lines |
| Transcript text | Not printed, downloaded, or archived |

This resolves the earlier `RequestBlocked` vs `IpBlocked` ambiguity: the provider returned **`IpBlocked`**, not the playability-level bot-detection `RequestBlocked` class.

## Pre-deployment production runtime (2026-10-26)

| Item | Verified value |
|---|---|
| Host | `minion-26` |
| Service | `ref-api.service` (systemd user unit), active since 2026-10-26T06:02:30Z |
| Process | PID 1799, `/home/draeician/.local/share/ref-services/ref-api/bin/python .../bin/ref-api --host 0.0.0.0 --port 8000` |
| Python | 3.13.17 (service venv) |
| Package | `ref-cli 1.6.12b1.dev104+g0e5d9828e` |
| Installed source | `file:///home/draeician/.local/share/ref-services/src-ref` (non-editable) |
| Source revision | `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2` — **same as current `origin/main`** |
| `youtube-transcript-api` | 1.2.4 |
| Other relevant deps | google-api-python-client 2.201.0, fastapi 0.161.0, uvicorn 0.54.0, yt-dlp 2026.10.21 |
| `/health` | `{"status":"ok","version":"1.6.12b1.dev104+g0e5d9828e"}` |
| Pipx (not the running service) | `ref-cli` 1.6.12b1.dev104+g0e5d9828e, Python 3.14.4, VCS install at the same SHA; `local-transcribe 0.7.0`; `lt` on the login `PATH` but not on the service `PATH` |
| Service `PATH` | `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin:/snap/bin` — no `~/.local/bin`, so no `lt` |

The deployed source matches `main`; this is not a stale-checkout problem. `ref-api` on `~/.local/bin` points at the pipx venv, but the running unit invokes the dedicated `ref-services` venv directly.

### Enhanced handler import check

- `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the service venv.
- `import get_transcript` from the service venv fails with `ModuleNotFoundError: No module named 'get_transcript'`.
- `get_transcript.py` is absent from the installed distribution `RECORD` and from site-packages.
- Cause: `pyproject.toml` packages only `ref_cli` and `ref_api`; the repository-root `get_transcript.py` is not installed. The import shim in `cli.py` only adds the site-packages directory to `sys.path`, so a normal wheel/venv/VCS install cannot import it.

## Cooldown state at diagnosis (historical)

Configured transcripts directory: `/home/draeician/references/transcripts` → `/opt/md2/music/youtube/transcripts`.  
Marker: `/home/draeician/references/transcripts/.youtube-transcript-block.json`.

```json
{
  "blocked_until": 1793029033.066984,
  "duration_seconds": 3600,
  "lease_expires_at": 0.0,
  "lease_owner": null,
  "next_probe_at": 0.0,
  "set_at": 1793025433.066984,
  "version": 1
}
```

- `set_at` = **2026-10-26T14:37:13Z**
- `blocked_until` = **2026-10-26T15:37:13Z**
- At investigation time (~16:06Z) the cooldown was **expired**, no lease was held, and `next_probe_at` was `0.0`.
- The cooldown is re-established only when an actual recovery probe runs and is blocked. Rows during an active cooldown are skipped without a provider call.
- Repeated failures do continually re-establish the cooldown: probes at 12:31:57Z (after the 11:30 cooldown expired) and 14:37:13Z (after the 12:31 cooldown expired) both re-entered a fresh 3600-second block.
- No cooldown state was removed, reset, or edited.

## Timeline evidence

Journal retention begins 2026-10-22T21:55Z.

| Event | Timestamp (UTC) | Evidence |
|---|---|---|
| Last successful direct retrieval | **2026-10-25T18:36:26** | `references.md` row for `rRtN1pN6KQw` with transcript JSON path; JSON mtime 2026-10-25T12:32:18Z. The NFS mount clock is ~6h04m behind the app host (confirmed against the pending file), so the JSON was written at ingest time. |
| First failure after last success / transition | **2026-10-26T00:38:09** | `aZMKzHhlTh8` row becomes `Transcript unavailable (queued in transcript-pending.md)`; same-second cooldown warning. |
| Block warning 1 | 2026-10-26T00:38:09Z | cooldown until 01:38:08Z |
| Block warning 2 | 2026-10-26T05:46:36Z | cooldown until 06:46:36Z |
| Block warning 3 | 2026-10-26T11:30:50Z | cooldown until 12:30:50Z |
| Block warning 4 | 2026-10-26T12:31:57Z | cooldown until 13:31:57Z |
| Block warning 5 | 2026-10-26T14:37:13Z | cooldown until 15:37:13Z |
| Controlled live test | **2026-10-26T18:13:09Z** | `IpBlocked` after 1.257s; no retry; block still active |

There were 10 cooldown warnings total in the retained journal since 2026-10-22, including 5 on 2026-10-24 and 5 on 2026-10-26.

## Last 50 YouTube ingests — measured counts

Sample window: 2026-10-25T14:53:30Z through 2026-10-26T15:05:01Z (last 50 YouTube rows in `references.md`). Classification was correlated with journal cooldown timestamps, transcript JSON presence/mtime, and queue records; it was not inferred from JSON existence alone.

| Category | Count | Share |
|---|---:|---:|
| Direct caption retrieval (JSON path, ingest-time file) | 15 | 30% |
| Actual provider attempt blocked by YouTube | 5 | 10% |
| Skipped during active cooldown (no provider attempt) | 26 | 52% |
| Pending-file fallback, unexplained by cooldown | 3 | 6% |
| Unexpected XML/parse failure (`no element found: line 1, column 0`) | 1 | 2% |
| **Total** | **50** | **100%** |

Additional measurements:

- **34 of 50** rows have a pending-file placeholder.
- **31 of those 34** are post-2026-10-26T00:38; **5** were actual blocked probes and **26** were cooldown skips.
- **0** of the 50 video IDs appear in any local-transcribe queue record.
- **0** new local-transcribe/Whisper jobs were created for this sample.
- Last queue record created: **2026-10-24T21:03:29Z** (`youtube:KHjNVmpHO60`, completed). Queue counts at inspection: pending 0, processing 1, retry 0, completed 1593, failed 183, cancelled 21.
- Pending file: 792 YouTube URLs, last line `https://www.youtube.com/watch?v=VhrtlfTyqp4` (the 15:05Z ingest).

## Failure classification

- **`RequestBlocked` / `IpBlocked` family:** confirmed 5 times in the last 50 (plus 5 earlier warnings on 2026-10-24). The code only records the generic `("blocked", message)` failure and emits one warning, so the historical subclass was not in the journal. The controlled test on the same host/path returned `IpBlocked`, which is the best current classification for this block. In this library, HTTP 429 and a reCAPTCHA challenge both surface as `IpBlocked`; playability-level bot detection surfaces as `RequestBlocked`.
- **`NoTranscriptFound` / `TranscriptsDisabled`:** not explicitly evidenced. The 3 pre-block pending rows (`RPrgNFnbAhQ`, `Jy7FMagiTFk`, `_vaNn_xFS_Y`) could be genuine missing captions, but the logs do not retain the method/message. No `TranscriptsDisabled` or `NoTranscriptFound` text appears in the journal.
- **Network / unexpected:** one row (`_sY20BGB1Tg`, 2026-10-25T15:32:12Z) stores `No transcript available (Legacy method: no element found: line 1, column 0)`. This is an XML/response parse failure, not a confirmed missing caption; it was not queued because the message does not match the no-transcript phrase list.
- **Import error:** enhanced handler `ModuleNotFoundError` is present in production, but it is a packaging defect, not a per-video failure. The legacy path is used.
- **Cooldown skips:** 26 of the last 50 were not provider attempts. `begin_probe()` returned `allowed=False`, and `fetch_youtube_transcript()` returned a synthetic `("blocked", message)`, which then queued/fallback-pended the URL. These are not evidence that captions were unavailable.
- **Local transcription:** no actual Whisper jobs were created for the sample. The fallback file is the legacy pending queue, not the durable local-transcribe queue.

## Exact fallback decisions

1. `fetch_youtube_transcript()` calls `transcript_block.begin_probe(TRANSCRIPTS_DIR)`.
2. During an active cooldown/backoff/lease, `begin_probe()` returns `allowed=False`; no provider call occurs, and the caller receives `("blocked", message)`.
3. `_fetch_youtube_transcript_provider()` also rechecks `is_blocked()` before the legacy fallback, so a block discovered during the enhanced attempt cannot be bypassed by the legacy path.
4. `resolve_transcript_failure_placeholder()` calls `add_url_to_pending_file()` for blocked or no-transcript failures.
5. `add_url_to_pending_file()` tries `local_transcribe.queue_api.enqueue_youtube_safe`; the service venv still does not contain `local_transcribe`, so this raises `ImportError`.
6. It then resolves the explicit `lt` path and queue directory from `REF_LOCAL_TRANSCRIBE_LT` / `REF_LOCAL_TRANSCRIBE_QUEUE_DIR`; as of the 2026-10-27 deployment both are configured and verified, so it invokes `lt queue add --queue-dir` successfully.
7. The reference row becomes `Transcript unavailable (local-only mode; queued for local-transcribe worker; execution <id>)`.

Before PR #22, the service had neither `local_transcribe` nor an explicit `lt`/queue path, so every failure fell back to `transcript-pending.md`. That is no longer the deployed behavior.

## Root cause and unresolved hypotheses

**Established:**

1. The provider returned `IpBlocked` to this host's IP at 2026-10-26T18:13:09Z; the block was already active at 2026-10-26T00:38:09Z and persisted through the controlled test. The cooldown then suppresses all requests for an hour.
2. Every request inside the cooldown is treated as unavailable and sent to the pending-file fallback without a caption attempt.
3. Before PR #22, the service could not reach the durable local-transcribe queue (missing module and missing `lt`/queue config), so failures accumulated in `transcript-pending.md` rather than becoming Whisper jobs. PR #22 was deployed on 2026-10-27 with explicit `lt`/queue configuration and verification; the smoke capture became a durable completed job.
4. The enhanced handler is not importable in any normal installation; production is using only the legacy path.
5. Current logs do not preserve the provider exception class/message or successful retrieval events; the controlled test bypassed this gap by calling the library directly.

**Unresolved:**

- What caused YouTube to classify this IP as blocked (request history vs cloud/provider reputation) is not exposed. The class confirms an IP-level block (`IpBlocked`), but does not distinguish HTTP 429 from a reCAPTCHA challenge page.
- Are the 3 pre-block pending rows genuine missing captions or another failure? Logs are insufficient.
- Are the blocked/skipped videos actually caption-capable? No provider attempt was made for 26 of them, so availability is unknown.
- Is the pending file being imported by the GPU worker? **No.** `queue.legacy_pending_file` remains unset and the worker’s default pending path does not exist; the 792-URL NFS pending file is untouched. This is intentional for this rollout.

There is no evidence that successfully fetched captions are being misclassified as unavailable. The misclassification is limited to (a) cooldown skips being reported as unavailable and (b) non-block unexpected errors being rendered as “No transcript available”.

## Corrective implementation (2026-10-26)

Branch: `fix/durable-transcript-queue` (based on `main` at `53f4c0c`), merged as PR #22 and deployed on 2026-10-27.

- Added `src/ref_cli/transcript_queue.py`: mode resolution, absolute-path validation, queue-directory resolution, `queue.id` parsing, and expected-UUID verification.
- Added `REF_YOUTUBE_TRANSCRIPT_MODE` / `youtube_transcript_mode` with `remote_first` (default) and `local_only`.
- `local_only` reuses an existing transcript JSON or queues the video; it never calls `youtube-transcript-api` and does not read or modify cooldown markers.
- Queue order is in-process `enqueue_youtube_safe` → explicit `lt queue add --queue-dir` → `lt` on `PATH` → `transcript-pending.md`.
- Explicit queue settings: `REF_LOCAL_TRANSCRIBE_LT`, `REF_LOCAL_TRANSCRIBE_QUEUE_DIR`, `REF_LOCAL_TRANSCRIBE_QUEUE_UUID` (and matching config keys). Explicit paths must be absolute.
- CLI output parsing tolerates warnings and ANSI decoration; malformed output fails safely to the pending file.
- Status messages distinguish YouTube block, no captions, local-only skip, durable enqueue, duplicate/already-completed, and pending-file-only fallback.
- Pending-file writes now return a failure result if the file cannot be updated; ref does not claim the URL was recorded when it was not.
- Updated `README.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, and both config templates.
- Added `tests/test_transcript_queue_modes.py` (17 tests) and updated blocking expectations in `tests/test_transcript_blocking.py`.
- Full suite: **406 passed, 1 warning** in the isolated test venv. A post-change wheel build succeeded at `1.6.12b1.dev109+gf158f2d1c` (newer than production `dev104`).

## Worker / backlog findings (read-only)

- Worker host `aether`: PID `2696`, `lt worker run --standby`, systemd user unit `local-transcribe-worker.service`, active since **2026-10-25T15:28:03Z**, holds the NLM lock.
- Worker `state.json` heartbeat at pre-deployment inspection was **2026-10-25T15:28:05Z**. This is normal while idle; the heartbeat updates only when a job is claimed, so it is not a liveness indicator. During the smoke test it updated and showed the active child execution.
- Worker config `/home/draeician/.config/local-transcribe/config.yaml` contains:
  ```yaml
  queue:
    path: /opt/md2/music/youtube/transcripts/transcription-queue
    expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
    expected_nfs_version: 3
    expected_server: depot.draeician.com
    expected_export: /mnt/tank/md2
  ```
- `queue.legacy_pending_file` is unset. The default `~/references/transcripts/transcript-pending.md` does not exist on `aether`.
- The real pending file is `/opt/md2/music/youtube/transcripts/transcript-pending.md` and currently has **792 URLs**. The worker therefore never imports this backlog; it is running, but it is not watching that file.
- Queue counts at inspection: pending 0, processing 1, retry 0, completed 1593, failed 183, cancelled 21.
- Do **not** set `legacy_pending_file` as part of this change: it would immediately import the 792-URL backlog. That requires separate authorization and an explicit capacity/priority decision.

## Production deployment — 2026-10-27

**Status: DONE.** Approved merge commit `30fdc69f1837b28a27d0853ff678a5578816c3ab`; installed package `ref-cli 1.6.12b1.dev111+g30fdc69f1` on Python `3.13.17`.

### Predeployment checks

- `main` clean at the approved merge commit; PR #22 merged; CI `pytest` SUCCESS.
- Prior production: `ref-cli 1.6.12b1.dev104+g0e5d9828e`, source revision `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2`, dedicated venv `/home/draeician/.local/share/ref-services/ref-api`.
- NFS queue mounted read/write at `/opt/md2/music/youtube/transcripts/transcription-queue` (`nfs4`, `depot.draeician.com:/mnt/tank/md2`); `queue.id` UUID matched `8c6fc098-8cbe-41ae-9689-dd759797a582`; 1.2T free (filesystem 99% used).
- `/home/draeician/.local/bin/lt` is `local-transcribe 0.7.0`; `lt queue add --help` includes `--queue-dir`.
- `aether` worker active: PID `2696`, `local-transcribe-worker.service`, started `2026-10-25T15:28:03Z`, NLM lock held. The API was idle (last request was `/health`; no active connections).

### Rollback preservation

Backup directory: `/home/draeician/.local/share/ref-services/deploy-backups/20261027T0035Z-pr22`.

Contains the prior unit, `config.yaml`, freeze, `direct_url` metadata, source revision, old wheel `ref_cli-1.6.12b1.dev104+g0e5d9828e`, queue identity/state/counts, archive hashes/stat metadata, and `show_notes_queue/jobs.json`. Full archive was not copied; `references.md` and pending-file hashes were recorded.

### Configuration and install

- Created `~/.config/ref/ref-api.env` (mode `0600`) with the four approved `REF_*` settings.
- Added `EnvironmentFile=-/home/draeician/.config/ref/ref-api.env` to the existing `ref-api.service`; `systemd-analyze --user verify` passed.
- Checked out `30fdc69f1837b28a27d0853ff678a5578816c3ab` in `/home/draeician/.local/share/ref-services/src-ref` and installed into the dedicated venv with `uv pip install --force-reinstall --no-deps`.
- `ref-api --help` exited 0; installed metadata/module version is `1.6.12b1.dev111+g30fdc69f1`.
- Restarted `ref-api.service` gracefully at `2026-10-27T00:40:39Z` during an idle window (old PID `1799` shut down cleanly; new PID `481515`).
- `/health` returned `{"status":"ok","version":"1.6.12b1.dev111+g30fdc69f1"}`. The running process environment contained all four approved settings.

### Smoke test

One manual `POST /urls` at `2026-10-27T00:42:09Z` for **`jNQXAC9IVRw`** (“Me at the zoo”), which was absent from `references.md` and the queue.

| Field | Result |
|---|---|
| HTTP result | `200`, status `added` |
| Reference status | `Transcript unavailable (local-only mode; queued for local-transcribe worker; execution 5d7be5b4-8401-4d4c-a9fd-77081c874b38)` |
| Execution ID | `5d7be5b4-8401-4d4c-a9fd-77081c874b38` |
| Source key | `youtube:jNQXAC9IVRw` |
| Queue status | **completed** at `2026-10-27T00:42:17Z` |
| Worker visibility | `aether` worker claimed it and ran `yt-dlp` for that execution at `00:42:13Z`; queue record and key record are present |
| Worker output | `/home/draeician/references/transcripts/jNQXAC9IVRw.json` on **aether**, 399 bytes |
| Caption provider | No `youtube-transcript-api` call; status came from the `local_only` branch; no block/provider warnings; cooldown marker remains absent |
| Service errors | No error/exception/traceback markers in the deployment journal window |

**Side effect:** the single submitted URL triggered the existing show-note discovery worker, which automatically added two child YouTube rows and queue jobs:

- `youtube:0PT5c1z3LL8` — execution `0e5878f4-af13-4b6d-a43e-2811ecf5be48` (completed)
- `youtube:RRBN_4L09Mg` — execution `0b2f2e45-e793-485b-afd2-4d7d71d76f91` (completed)

No additional manual captures were run. These child jobs are legitimate output of the existing show-note feature, not a retry of the smoke test. All three queue executions (primary and both children) were completed by the worker.

**Backlog:** `/opt/md2/music/youtube/transcripts/transcript-pending.md` remained unchanged: 792 lines, SHA-256 `ba80807504d6d13c5a495453e04fb8c4f6ee61ba8277e6930e55fcc02f50713d`. No `queue.legacy_pending_file` change was made on `aether`.

## Rollback

Rollback was not required. If needed:

1. Restore `~/.config/systemd/user/ref-api.service` from the backup and remove `~/.config/ref/ref-api.env` (or set `REF_YOUTUBE_TRANSCRIPT_MODE=remote_first`), then `systemctl --user daemon-reload`.
2. Check out `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2` in `src-ref` and install the preserved old wheel `ref_cli-1.6.12b1.dev104+g0e5d9828e` with `uv pip install --force-reinstall --no-deps`.
3. Restart `ref-api.service` in an idle window and verify `/health` reports `dev104`.
4. Do not restore archive snapshots over newer data. Preserve queue jobs and reference rows; rollback does not remove already-created work.

## Risks and limitations

- `local_only` intentionally disables direct caption retrieval even after YouTube unblocks this IP. Switch back to `remote_first` to resume caption attempts.
- The pipx `lt` is `local-transcribe 0.7.0`; `--queue-dir` support must remain available. A future downgrade would fall back to the pending file.
- Queue identity depends on the NFS mount and `queue.id`; a mismatch or unavailable mount fails safely to the pending file.
- The 792-URL backlog is still not imported. Draining it may create a large burst of local transcription work.
- The worker heartbeat can look stale while idle; check the process/unit and lock, not just `state.json`. During the smoke test it updated and reported the active child execution.
- ~~**Remaining issue:** the worker writes completed transcript JSON to its local `aether:/home/draeician/references/transcripts` path, not the shared NFS archive.~~ **Superseded:** Aether's `~/references/transcripts` now symlinks to `/opt/md2/music/youtube/transcripts`, the missing `.generations` files were copied and SHA-256 verified with zero conflicts, and `minion-26` can read all three smoke-test transcripts. The Phase 3 reconciler consumes the configured shared path rather than the old queue `output_path`.
- The two show-note child jobs completed after the smoke capture; the queue drained cleanly on `aether`.
- The NFS filesystem is 99% used (1.2T free); continued queue growth should be monitored.

## Exactly one recommended next action

**Authorize a separately scheduled production deployment of Phase 3 on `minion-26` (install the merged package, restart `ref-api`, and verify the three smoke-test rows plus the backup), because the reconciler is implemented and tested but this task did not deploy it; do not import the 792-URL backlog or change Aether's worker configuration.**

## Safety

The deployment was explicitly authorized. One manual smoke capture was submitted; it triggered the existing show-note discovery of two child URLs. No direct YouTube transcript probe was made from `minion-26`; no cookies, proxies, bulk requests, backlog import, worker configuration change, worker restart, transcript deletion, or reference deletion occurred. The 792-URL pending file was not modified. The cooldown marker was absent before and after. Configuration, package, queue, and archive metadata were backed up before changes.

## Code change status

PR #22 is merged and deployed. The corrective implementation is active on `minion-26`: configurable `remote_first`/`local_only` mode, explicit durable queue submission, safe pending fallback, tests, and docs. The enhanced `get_transcript.py` packaging defect remains out of scope. The `references.md` parser observation remains non-causal and out of scope.
