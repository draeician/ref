# HANDOFF — YouTube transcript routing investigation

**Date:** 2026-10-26 (UTC)  
**Mode:** diagnostics only; no application code, production config, service, queue, or archive changes were made.  
**Repository:** https://github.com/draeician/ref  
**Scope:** why recent YouTube ingests are routed to local-transcribe/Whisper instead of using captions directly.

## Executive diagnosis

**Primary cause (high confidence): a real YouTube provider IP block, amplified by the cooldown design.** Direct caption retrieval worked through **2026-10-25T18:36:26Z**. The first post-success failure was **2026-10-26T00:38:09Z**, when the provider returned a block-family error (`RequestBlocked`/`IpBlocked`). The cooldown then suppressed every subsequent transcript provider call for one hour. Each recovery probe after cooldown expiry was blocked again, so the cycle repeated at 05:46, 11:30, 12:31, and 14:37 UTC.

**Secondary cause (high confidence): the local-transcribe queue is not reachable from the running service.** The service virtualenv does not contain `local_transcribe`, and the systemd service `PATH` does not contain `lt`; `lt` also has no configured queue path on this host. Every failure therefore takes the final fallback: append to `transcript-pending.md`. No new local-transcribe/Whisper queue job has been created since **2026-10-24T21:03:29Z**, and none of the recent sample video IDs appear in the queue.

**Latent defect (high confidence): the enhanced `get_transcript.py` handler is not packaged and cannot be imported in production.** `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the running service. The legacy provider path still worked until the IP block, so this is not the trigger, but it removes the enhanced path and contributes to poor diagnostics.

**Diagnostics gap (high confidence): the original provider exception is hidden.** `finish_probe` logs only a generic cooldown warning; the provider exception class/message is logged at `debug`/`info` levels that are not emitted by the service. The exact block subtype (429 `IpBlocked` vs bot-detection `RequestBlocked` vs another cause) cannot be established from current logs.

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

- **`RequestBlocked` / `IpBlocked` family:** confirmed 5 times in the last 50 (plus 5 earlier warnings on 2026-10-24). The code only records the generic `("blocked", message)` failure and emits one warning; the exact subclass and provider message are not in the journal. A 429 would surface as `IpBlocked`; bot detection would surface as `RequestBlocked`. This distinction is unresolved.
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
5. `add_url_to_pending_file()` tries `local_transcribe.queue_api.enqueue_youtube_safe`; in the service venv this raises `ImportError`.
6. It then checks `shutil.which("lt")`; the service `PATH` has no `lt`, so it skips the CLI path and calls `_pending_file_fallback_result()`.
7. The reference row becomes `Transcript unavailable (queued in transcript-pending.md)`.

Even if `lt` were on `PATH`, `lt queue path` on this host reports no configured queue directory, so the CLI path would also fall back. The durable queue exists at `/opt/md2/music/youtube/transcripts/transcription-queue` and has a valid `queue.id`, but the producer environment is not configured to use it.

## Root cause and unresolved hypotheses

**Established:**

1. The provider is returning a block-family error to this host's IP; the cooldown then suppresses all requests for an hour.
2. Every request inside the cooldown is treated as unavailable and sent to the pending-file fallback without a caption attempt.
3. The service cannot reach the durable local-transcribe queue (missing module and missing `lt`/queue config), so failures accumulate in `transcript-pending.md` rather than becoming Whisper jobs.
4. The enhanced handler is not importable in any normal installation; production is using only the legacy path.
5. Current logs do not preserve the provider exception class/message or successful retrieval events.

**Unresolved:**

- Is the block a 429 rate limit (`IpBlocked`) or bot/recaptcha detection (`RequestBlocked`)? The cooldown warning cannot distinguish them.
- Are the 3 pre-block pending rows genuine missing captions or another failure? Logs are insufficient.
- Are the blocked/skipped videos actually caption-capable? No provider attempt was made for 26 of them, so availability is unknown.
- Is the pending file being imported by the GPU worker? No queue evidence exists since 2026-10-24T21:03:29Z; the queue worker state shows a last heartbeat of 2026-10-25T15:28:05Z.

There is no evidence that successfully fetched captions are being misclassified as unavailable. The misclassification is limited to (a) cooldown skips being reported as unavailable and (b) non-block unexpected errors being rendered as “No transcript available”.

## Exactly one recommended next action

**Authorize one controlled, single-video live diagnostic — and only one — now that the cooldown is expired.** Use a known-captioned video such as `rRtN1pN6KQw` (last confirmed direct success), call the legacy `YouTubeTranscriptApi().fetch()` path once, and capture the raw exception class/message and result. Do not enqueue, do not touch the pending file, do not use cookies/proxies, and do not make bulk requests.

This one test distinguishes a persistent IP-level block from a code/packaging defect. If it returns `RequestBlocked`/`IpBlocked`, the next work is IP/block remediation; if it succeeds, the next work is tracing why the ref path fails despite direct library access. No code change should be made before that result.

## Safety

No live YouTube probe was run during this investigation. No cookies, proxies, bulk requests, queue mutations, archive edits, service restarts, package installs, or production configuration changes were made. The cooldown marker was read only.

## Code change status

No application code change is recommended yet. After the controlled test, likely follow-ups are:

- package `get_transcript.py` as an importable module (or move the handler into `ref_cli`);
- log the provider exception class/message at warning/error level and log direct successes;
- fix the pending-file queue integration or explicitly configure the producer to use the durable queue;
- correct the `references.md` parser's greedy title match, which currently misparses rows whose placeholder contains parentheses (observed during sampling; not causal to this issue).

These are diagnostics findings, not authorized changes.
