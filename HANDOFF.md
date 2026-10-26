# HANDOFF — YouTube transcript routing investigation

**Date:** 2026-10-26 (UTC)  
**Mode:** corrective implementation; one authorized live fetch was performed during diagnosis. No production config, service, queue, or archive changes were made.
**Repository:** https://github.com/draeician/ref  
**Scope:** why recent YouTube ingests are routed to local-transcribe/Whisper instead of using captions directly.

## Executive diagnosis

**Primary cause (confirmed): YouTube is blocking direct caption retrieval from `minion-26`.** A controlled single-video test at **2026-10-26T18:13:09Z** returned `youtube_transcript_api._errors.IpBlocked` after 1.257s. `IpBlocked` is a subclass of `RequestBlocked` and represents an IP-level block; this library raises it for HTTP 429 or a reCAPTCHA challenge page. The numeric status was not exposed. The block began by **2026-10-26T00:38:09Z** and was still active at 18:13Z. The cooldown then suppressed every subsequent transcript provider call for one hour; each recovery probe was blocked again, so the cycle repeated at 05:46, 11:30, 12:31, and 14:37 UTC.

**Secondary cause (high confidence): the local-transcribe queue is not reachable from the running service.** The service virtualenv does not contain `local_transcribe`, and the systemd service `PATH` does not contain `lt`; `lt` also has no configured queue path on this host. Every failure therefore takes the final fallback: append to `transcript-pending.md`. No new local-transcribe/Whisper queue job has been created since **2026-10-24T21:03:29Z**, and none of the recent sample video IDs appear in the queue. The corrective implementation adds explicit absolute `lt`/queue configuration, queue identity verification, and a `local_only` mode so the producer does not need `local_transcribe` installed in its own venv. Deployment is still required.

**Latent defect (high confidence): the enhanced `get_transcript.py` handler is not packaged and cannot be imported in production.** `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the running service. The legacy provider path still worked until the IP block, so this is not the trigger, but it removes the enhanced path and contributes to poor diagnostics.

**Diagnostics gap (high confidence): production logs hide the provider exception.** The controlled test identified `IpBlocked`, but the running service logs only the generic cooldown warning; it does not record the exception class/message. The test also confirmed that the exception object does not expose a numeric HTTP status.

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

## Verified production runtime

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

## Cooldown state (read-only)

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
5. `add_url_to_pending_file()` tries `local_transcribe.queue_api.enqueue_youtube_safe`; in the deployed service venv this raises `ImportError`.
6. It then resolves an explicit `lt` path from `REF_LOCAL_TRANSCRIBE_LT` / config; the deployed service has neither, so it skips the CLI path and calls `_pending_file_fallback_result()`.
7. The reference row becomes `Transcript unavailable (queued in transcript-pending.md)`.

Even if `lt` were on `PATH`, `lt queue path` on this host reports no configured queue directory, so the CLI path would also fall back. The durable queue exists at `/opt/md2/music/youtube/transcripts/transcription-queue` and has a valid `queue.id`, but the deployed producer environment is not configured to use it. The corrective code adds that explicit configuration; deployment is pending.

## Root cause and unresolved hypotheses

**Established:**

1. The provider returned `IpBlocked` to this host's IP at 2026-10-26T18:13:09Z; the block was already active at 2026-10-26T00:38:09Z and persisted through the controlled test. The cooldown then suppresses all requests for an hour.
2. Every request inside the cooldown is treated as unavailable and sent to the pending-file fallback without a caption attempt.
3. The service cannot reach the durable local-transcribe queue (missing module and missing `lt`/queue config), so failures accumulate in `transcript-pending.md` rather than becoming Whisper jobs. The corrective code adds explicit `lt`/queue configuration and verification; deployment is pending.
4. The enhanced handler is not importable in any normal installation; production is using only the legacy path.
5. Current logs do not preserve the provider exception class/message or successful retrieval events; the controlled test bypassed this gap by calling the library directly.

**Unresolved:**

- What caused YouTube to classify this IP as blocked (request history vs cloud/provider reputation) is not exposed. The class confirms an IP-level block (`IpBlocked`), but does not distinguish HTTP 429 from a reCAPTCHA challenge page.
- Are the 3 pre-block pending rows genuine missing captions or another failure? Logs are insufficient.
- Are the blocked/skipped videos actually caption-capable? No provider attempt was made for 26 of them, so availability is unknown.
- Is the pending file being imported by the GPU worker? No queue evidence exists since 2026-10-24T21:03:29Z; the queue worker state shows a last heartbeat of 2026-10-25T15:28:05Z.

There is no evidence that successfully fetched captions are being misclassified as unavailable. The misclassification is limited to (a) cooldown skips being reported as unavailable and (b) non-block unexpected errors being rendered as “No transcript available”.

## Corrective implementation (2026-10-26)

Branch: `fix/durable-transcript-queue` (based on `main` at `53f4c0c`). No production deployment.

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
- Worker `state.json` heartbeat is **2026-10-25T15:28:05Z**. This is normal while idle; the heartbeat updates only when a job is claimed, so it is not a liveness indicator.
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

## Safe deployment plan (not executed)

1. Add these values to `~/.config/ref/ref-api.env` on `minion-26`:
   ```bash
   REF_YOUTUBE_TRANSCRIPT_MODE=local_only
   REF_LOCAL_TRANSCRIBE_LT=/home/draeician/.local/bin/lt
   REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/opt/md2/music/youtube/transcripts/transcription-queue
   REF_LOCAL_TRANSCRIBE_QUEUE_UUID=8c6fc098-8cbe-41ae-9689-dd759797a582
   ```
2. Install the merged ref-cli build into the `ref-api` venv using the established service-upgrade procedure, then restart `ref-api.service` **only with separate authorization**.
3. Verify a new capture reports `local_only`/queued status, the queue UUID matches, and a new pending queue record appears. Do not probe YouTube from `minion-26`.
4. Leave the worker configuration unchanged for now. The worker is already active and consumes durable queue jobs; the 792-URL backlog remains untouched.

## Rollback

- Set `REF_YOUTUBE_TRANSCRIPT_MODE=remote_first` (or remove the mode variable), restore the previous package build, and restart `ref-api.service`.
- Queue jobs already submitted remain valid and are not rolled back. Pending-file entries remain untouched.
- If the explicit queue path/UUID is wrong, remove those variables to return to legacy `lt`-on-`PATH`/pending-file behavior.

## Risks and limitations

- `local_only` intentionally disables direct caption retrieval even after YouTube unblocks this IP. Switch back to `remote_first` to resume caption attempts.
- The pipx `lt` is `local-transcribe 0.7.0`; `--queue-dir` support must remain available. A future downgrade would fall back to the pending file.
- Queue identity depends on the NFS mount and `queue.id`; a mismatch or unavailable mount fails safely to the pending file.
- The 792-URL backlog is still not imported. Draining it may create a large burst of local transcription work.
- The worker heartbeat can look stale while idle; check the process/unit and lock, not just `state.json`.
- No live production verification of the new producer path has been performed.

## Exactly one recommended next action

**Authorize deployment of the merged corrective change to `minion-26` with `REF_YOUTUBE_TRANSCRIPT_MODE=local_only` and the explicit queue path/UUID above; do not probe YouTube from this host and do not import the 792-URL backlog until separately approved.** The code change is complete; production deployment is the remaining step.

## Safety

One authorized live YouTube probe was run at 2026-10-26T18:13:09Z. It returned `IpBlocked`; no retry was made. No transcript text was printed, downloaded, or archived. No cookies, proxies, bulk requests, queue mutations, archive edits, service restarts, package installs, or production configuration changes were made. The cooldown marker was read only. Worker/queue inspection was read-only. The corrective code was developed and tested in an isolated worktree/venv.

## Code change status

The corrective implementation is complete on `fix/durable-transcript-queue`: configurable `remote_first`/`local_only` mode, explicit durable queue submission, safe pending fallback, tests, and docs. It is not deployed. The enhanced `get_transcript.py` packaging defect remains out of scope. The `references.md` parser observation remains non-causal and out of scope.
