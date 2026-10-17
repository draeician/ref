# [fix] Issue #18 — ref-api show-note fan-out exceeds client timeout

- **Task ID:** d0c54a91
- **State:** IN-REVIEW (not QA-approved) — initial implementation was QA-rejected with five blocking defects; corrections implemented in commit `559767654a117dcc20564a3f4f39ab321476d20e` per corrective task `7e4c9b12`, awaiting independent architect QA before any merge/deploy.
- **Role:** Coder (OpenCode), with independent architect QA before merge.
- **Issue:** https://github.com/draeician/ref/issues/18
- **Branch:** `fix/issue-18-youtube-show-notes-timeout` (cut from protected `main` at `799b10f28dd3776a8d9904509d166368e289bb7c`).
- **PR:** ONE draft PR against `main` (exact number/URL recorded in `.codex/notes/agent-handoff.md` and current-task).
- **Canonical notes:** `.codex/notes/current-task.md` and `.codex/notes/agent-handoff.md`.
- **Priority:** High — confirmed production UX defect; no production deployment authorized for this new change.

## Operator incident / verified evidence

On `minion`, current `ref` CLI and running `ref-api` are **both** `1.6.12b1.dev79+g799b10f28`; `GET /health` returns `{"status":"ok","version":"1.6.12b1.dev79+g799b10f28"}`, and service is `active/running` with `NRestarts=0`. A request:

```text
ref https://www.youtube.com/watch?v=cB4d7KHIyNc
ref API at 127.0.0.1:8000 did not respond in time (read timeout).
```

The video is **already present** in `~/references/references.md` (one match), so the CLI timeout is NOT evidence the server failed to archive the parent. The client HTTP read timeout is **300 seconds** in `src/ref_cli/api_client.py`. Operator-provided journal excerpt:

- `2026-10-17T02:42:12Z`: `YouTube notes: start`, video `cB4d7KHIyNc`, description 1653 chars, **20** links found.
- `02:42:52Z`: 14th child reports `status=exists`.
- **8 min 03 sec gap** until `02:50:55Z` when next child (a YouTube playlist) reports `status=exists`.
- `02:50:54Z`: first confirmed YouTube transcript IP block logs 3600-second cooldown. **Issue #15 mitigation is active and working**; it did not fix HTTP latency.
- `02:51:08Z`: `YouTube notes: complete` scanned=20, found=20, added=0, exists=20, errors=0.

**Working hypothesis:** a show-note child pointing to a YouTube playlist expanded into full playlist video/transcript processing. This is strongly supported by log ordering but has not been experimentally proven to be the *only* delay. Instrument and regression-test the correct call path before changing behavior; never claim more than evidence supports.

## Code path and design constraint

- `src/ref_api/routes.py`: `POST /urls` returns only after `service.process_many`.
- `src/ref_api/service.py`: `process_one` synchronously invokes `ref_cli.process_url` under `_write_lock`; after parent ingest status `added` OR `exists`, it calls `_process_youtube_show_notes`, which loops over up to `MAX_YOUTUBE_SHOW_NOTE_LINKS=50`, recursively calls `process_one(link, _discover_youtube_links=False)` and does not return until ALL children finish. The flag disables recursive *show-note discovery*, **not** playlist/video traversal in `ref_cli.process_url`.
- `src/ref_cli/cli.py` YouTube playlist path loops over playlist videos and missing transcript lookups; an existing child can still do expensive enrichment. `_write_lock` serializes work and can delay other calls. `contextlib.redirect_stdout` is global-process state: beware asynchronous worker/thread safety.
- Existing external CLI consumers expect `ingest_urls`/POST response with `UrlResult` fields; do not silently change `added/existing/skipped/error` semantics.
- Increasing `DEFAULT_INGEST_TIMEOUT`, limiting the whole request to 50 (already capped), or disabling show notes entirely **is not an acceptable fix**.

## Required implementation outcome

**Separate a parent video's API response from potentially unbounded show-note child processing**, while keeping link archival reliable.

1. **Bound the HTTP path**: a single YouTube parent ingest must be able to return its parent `added`/`exists` result promptly and independently of slow show-note children. A deterministic test should block a child with an event and show `POST /urls` returns before release of that child (no 300s waits). Don't report show-note children as completed while they are still running.
2. **Reliable continuation**: preserve the automatic handling of discovered URLs; the preferred approach is a **durable, restart-recoverable, deduplicating local work queue** for show-note discovery/child ingestion. Simple ephemeral background threads or FastAPI `BackgroundTasks` alone are not durable and can lose work at restart. If engineering exploration finds a smaller equally reliable approach, document the alternative and proof before implementing. Queue storage belongs beside archive-owned state, **not** in git; support at-least-once/recovery, bounded retries/backoff, explicit failure visibility and idempotent archive operations.
3. **Prevent child playlist explosion**: a playlist URL encountered *as an automatically discovered show-note child* must not trigger full synchronous playlist traversal during that parent request, nor recursive unbounded cascades in the continuation worker. Record/queue the playlist **link** safely and document the handling policy. **Directly submitted playlists** must retain their existing explicit processing behavior. Preserve safe-link filtering/50-link cap and dedupe.
4. **Concurrency and integrity**: parent and child processing must preserve `references.md` write serialization, existing `added/existing/skipped/error` semantics, `--force` behavior for explicit input, and crash/duplicate retry correctness. Do not lose the parent result when child tasks fail. Avoid global `sys.stdout` capture races in concurrent execution.
5. **Preserve issue #15**: tested cross-process transcript cooldown marker, single recovery probe, queue-first local-transcribe `enqueued/existing_active/requires_force` and `transcript-pending.md` fallback. Do not introduce repeated remote transcript attempts during cooldown.
6. **Observability**: log job/video ID, number of queued/completed/failed child URLs, bounded per-item timings and reasons, and unfinished queue depth without logging secrets. Provide a supported way to see whether a timed-out previous request is already archived or still has outstanding child jobs. Keep user-visible CLI messages accurate (e.g. `Show-note links queued`, not `complete`).
7. **Operational behavior**: safe worker initialization/shutdown with uvicorn/service lifecycle; no unguarded loss of accepted jobs or unbounded concurrency; service restarts remain possible but do **not** claim to resolve the separate operator stop-in-flight `RemoteDisconnected` for other synchronous paths.

## Test requirements

Write **deterministic fail-before/fix-after tests** for:
- One slow/gated discovered link; API response returns before child is released, parent recorded exactly once, child eventually handled.
- The incident shape (20 discovered links including one playlist) with a slow playlist; no full nested playlist processing in parent request; show-note counts truthful.
- Concurrent/repeated submissions of the same YouTube parent/links: no double-fanout or inconsistent archive, sensible `exists` behavior.
- Crash/restart recovery of accepted pending child jobs (or alternative recovery proof), bounded failed-link retries/backoff and transparent errors.
- Existing single-user direct playlist processing remains unchanged.
- Preservation of cooldown behavior, local-transcribe queue-first fallback, and no new production network fetches in tests.
- Existing API and title/extraction regressions green.

No real production YouTube requests, no changes to the user's `~/references` archive, no service restarts or pipx modifications as part of coding/testing. Use isolated test paths and mocked network responses only.

## Workflow / delivery

1. Before local repository operations, create/verify WIP marker **outside** repo; inspect current local git status/WIP and preserve all unrelated changes. Use isolated worktree, not the active production checkout. Do not access or print `~/.ssh` or secrets.
2. Fetch the remote feature branch; read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, `.codex/notes/current-task.md`, this task, handoff, `src/ref_api/{routes,service,app}.py`, `src/ref_cli/{api_client,cli,youtube_extract,transcript_block}.py`, `tests/`, README.
3. Reproduce with focused tests/profiling; capture source-level timeline; propose and implement the smallest safe reliable change consistent with the outcome above. Document architecture and the meaning of parent success vs queued/failed show-note work.
4. Run `python -m pytest -q`, `python -m compileall -q src get_transcript.py`, `git diff --check`, plus focused deterministic regressions. Do not invent test results.
5. Update README, this task, current-task pointer and handoff with exact implementation, test evidence, risks, rollback and exactly ONE next step. Preserve the closed issue #15 facts and note issue #17 old-release deployment report is still open.
6. Commit using repo conventions, push **only** `fix/issue-18-youtube-show-notes-timeout`, create exactly one **draft** PR with `Fixes #18` against `main`, and verify successful PR-head-SHA GitHub Actions. The workflow currently runs push CI only for `main` and the old `fix/issue-15-...` branch: **do not claim a new-branch push CI run exists unless it actually does**.
7. End with `[REVIEW-REQUEST]`, exact PR URL/number, head SHA, changed-file scope, local/remote test evidence, design tradeoffs and any blockers. Independent architect reviews; **no merging or production deployment** without a fresh specific approval.

## Exit criteria

Parent video success is no longer hostage to automatic 20–50 link fan-out; a slow discovered playlist does not trigger synchronous nested processing; all accepted child jobs survive restart and are observable; existing direct playlist ingest and transcript-blocking/queue semantics pass regressions; current archiving is preserved; no unauthorized production impact.

## Exactly one next step

OpenCode: implement task d0c54a91 on `fix/issue-18-youtube-show-notes-timeout`, open a single draft PR to `main`, and request independent code/CI review.

---

## Implementation (OpenCode, issue #18)

**Approach.** The synchronous `_process_youtube_show_notes` loop was replaced with
`_enqueue_youtube_show_notes`: the parent `process_url` records the video and the
discovery step enqueues each discovered link into a durable local queue, then
returns immediately with a summary that reports `queued=N` (never a misleading
`complete`). A single daemon worker thread (started/stopped in the FastAPI
lifespan) drains the queue, routing every child through `process_one` under the
existing `_write_lock`.

**New files / changed paths.**

- `src/ref_api/show_notes_queue.py` (new) — file-backed, atomic-rewrite queue
  (`<references>/show_notes_queue/jobs.json`), dedup by URL for unfinished jobs,
  at-least-once `recover()` for `running` jobs, bounded retry/backoff up to
  `MAX_ATTEMPTS=5`, explicit `done`/`failed` terminal states.
- `src/ref_api/service.py` — enqueue path, `_suppress_playlist_expansion` flag,
  worker thread + `_drain_show_notes_queue`, `queue_status()`.
- `src/ref_api/app.py` — lifespan starts/stops the worker.
- `src/ref_api/routes.py` + `schemas.py` — `GET /queue` status endpoint.
- `src/ref_cli/cli.py` — `record_youtube_playlist_link` (single playlist entry
  without `playlistItems` expansion) + `_youtube_playlist_metadata`.
- `src/ref_cli/youtube_extract.py` — `is_youtube_playlist_url` (list= param,
  excludes radio/mix).
- `tests/test_show_notes_queue.py`, `tests/test_show_notes_worker.py` (new) and
  `tests/test_youtube_api_notes.py` (updated to the queued contract).

**Key behavior guarantees.**
1. Parent returns independently of slow children (tested with a `threading.Event`
   gate: `POST /urls` returns while the child is still blocked).
2. Discovered playlist children are recorded as a single entry (no expansion);
   directly submitted playlists keep `process_url` full expansion (both tested).
3. Dedup prevents double-fan-out on repeated/concurrent parent submissions.
4. Accepted jobs survive restart (`recover()`) and are retried with backoff.
5. Issue #15 cooldown/local-transcribe and `_write_lock` semantics unchanged.

**Local test evidence (Python 3.12.3, venv `/tmp/opencode/ref-issue-18-venv`).**
- `python -m pytest -q` → **355 passed** (336 prior + 19 new; 1 warning from
  Starlette/httpx deprecation, unrelated).
- `python -m compileall -q src get_transcript.py` → OK.
- `git diff --check` → clean.

**Risks / limitations.**
- The worker is single-process (the `ref-api` host); the queue is not intended to
  be shared across hosts. `redirect_stdout` remains global but all archive writes
  stay serialized under `_write_lock`, so concurrent request/worker processing is
  safe.
- Pre-existing, unchanged: a discovered *Reddit/community-post* child still uses
  `process_url`, whose internal outbound-link recursion is out of scope here
  (the incident was a playlist link, which is now explicitly handled).
- A discovered playlist still needs `YOUTUBE_API_KEY` (same as the parent video
  path); without it the child job retries then lands in the visible `failed` state.

**Rollback.** Revert to `main` `799b10f28dd3776a8d9904509d166368e289bb7c` restores
the prior synchronous behavior. The new queue state lives under
`~/references/show_notes_queue/` (never in git) and is inert with old code.

## QA corrections (OpenCode, task 7e4c9b12)

Architect QA rejected the initial implementation with five blocking defects. All
five were corrected in commit `559767654a117dcc20564a3f4f39ab321476d20e` and
seven deterministic regressions were added:

1. **Concurrency** — `_write_lock` no longer held across slow provider/network
   I/O; a CLI-level `_archive_lock` serializes only the short archive read/write
   critical sections, and stdout capture is thread-local. A second independent
   `POST /urls` returns while the worker is stuck in slow child work.
2. **Discovery off the parent path** — `process_one` enqueues a `discover` job;
   the worker fetches the card and batch-enqueues `ingest` jobs. Parent returns
   independently of a stalled/uncached `read_video_card`.
3. **Fail-closed queue** — corrupt/unreadable/schema-invalid `jobs.json` raises
   `QueueCorruptError` and is never overwritten; `/queue` exposes `corrupt`.
4. **Bounded history + dedup** — done work is not re-enqueued (failed jobs may
   retry), terminal history is compacted, and children are batch-enqueued.
5. **Worker lifecycle fence** — `stop()` leaves the singleton set while a slow
   drain is still in flight so `start()` cannot spawn a duplicate worker.

Full suite **362 passed** (355 prior + 7 new); `compileall` and `git diff --check`
clean. See `.codex/tasks/7e4c9b12-issue-18-qa-corrections.md` for the detailed
evidence.
