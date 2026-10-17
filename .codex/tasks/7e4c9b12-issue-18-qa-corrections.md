# [fix] Issue #18 — architect QA corrections for background show-note queue

- **Task ID:** 7e4c9b12
- **State:** OPEN — blocking merge and production deployment of PR #19.
- **Parent task:** `.codex/tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md`; issue https://github.com/draeician/ref/issues/18.
- **Existing draft PR:** https://github.com/draeician/ref/pull/19 — keep the SAME PR; no new PR.
- **Development branch:** `fix/issue-18-youtube-show-notes-timeout` (no push/merge to `main`).
- **Independently reviewed app-code SHA:** `2b0fba7e64888ce14a700281379a0de0778baf54`.
- **Base main:** `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Reviewed exact-head CI:** https://github.com/draeician/ref/actions/runs/38998361423 — PASS, direct job log 355 passed / 1 warning.
- **Canonical task/status:** `.codex/notes/current-task.md`; handoff: `.codex/notes/agent-handoff.md`.
- **Architect verdict:** CHANGES REQUIRED; new code is not QA-accepted for merger or production.

## Evidence and blocking defects

### 1. Slow background worker still blocks new HTTP ingests

In `src/ref_api/service.py`, `_process_queued_job` calls `process_one(child, _discover_youtube_links=False, _suppress_playlist_expansion=True)`. `process_one` holds process-wide `_write_lock` **across the entirety** of `ref_cli.process_url` / `record_youtube_playlist_link`, including slow remote HTTP and transcript retrieval. A concurrent NEW `POST /urls` waits behind the worker and can still time out at the same 300 seconds, even though the earlier parent request returned. `test_parent_returns_before_slow_child_released` only tests the request which enqueued the job *before* the worker took the lock; it does not test a second request while the worker is stuck.

**Required:** Prove with deterministic `threading.Event` regression that worker is already inside slow child provider work before *another* independent `POST /urls` begins, and that the second request's parent result returns promptly without waiting for that child. Keep archive writes and shared file updates serialized and safe; a naive removal of `_write_lock` is not acceptable. Safely separate potentially long external I/O from the short archive write/commit critical section, or implement an equally sound serialized-writer architecture. Address global `redirect_stdout` capture hazards if more concurrency is introduced. Do not claim arbitrary direct-parent network fetches have strict latency bounds unless designed/tested.

### 2. Show-note metadata discovery remains on parent response path

`process_one` still calls `_enqueue_youtube_show_notes` synchronously; that calls `_discover_youtube_show_note_links` -> `read_video_card`, which can perform external metadata retrieval (`fetch_youtube_video` via YouTube API/yt-dlp) on a cache miss. A stalled provider delays parent response, so `POST /urls` is not independent of show-note work.

**Required:** Move discovery of outbound links as well as their ingestion into a durable/recoverable continuation, or rigorously bound this discovery and demonstrate the parent returns independently of a blocked metadata lookup. Preserve child URLs, safe-link filtering and 50-link cap. Write a deterministic **uncached read_video_card blocked by Event** regression proving the parent returns without releasing the gate and the discovery job resumes after release. Handle discovery failure with retry/backoff, observability, and no lost work.

### 3. Corrupt/unreadable queue is silently treated as empty, risking loss

`ShowNotesQueue._load` silently treats `JSONDecodeError`, `OSError`, `ValueError`, and even a malformed schema as `{}` and sets `_loaded=True`. A later `enqueue` calls `_snapshot`, overwriting the original jobs table with new work. This silently discards pending/running jobs for a queue advertised as durable.

**Required:** Distinguish fresh/nonexistent queue from corrupt/unreadable existing queue. Fail closed, preserve the original bytes, surface clear log/status/operator action, and prohibit overwriting accepted jobs unless safe recovery is proven. Validate schema/required job fields and bounds before claiming/scheduling. Add test creating a queue with accepted jobs then simulating malformed/unreadable storage; verify old file is untouched, enqueue fails visibly, and no jobs are silently lost. Preserve atomic snapshots and filesystem persistence semantics.

### 4. Terminal-job history, duplicates and performance are unbounded

`enqueue` skips only `pending`/`running`; `done` and `failed` jobs remain in the dictionary indefinitely. Submitting an already-existing YouTube video after its children finished will enqueue those same links again, potentially repeat network calls and grow the JSON without bound. Every `enqueue` rewrites+fsyncs the entire queue; 50 links = 50 full rewrites; scale degrades as job history grows.

**Required:** Define deliberate, documented semantics for rediscovery and explicit retries. Avoid re-enqueue of recently/completely processed unchanged links by default, while permitting an intentional retry/refresh of failed jobs. Implement finite retention/compaction or a bounded-index/journal approach and batch/transactional enqueue for up to 50 child URLs where feasible, with no acknowledged work lost on partial failure. Add deterministic tests for resubmission after *completed* children and for bounded history/retention; verify counts and queue semantics remain truthful.

## Further lifecycle audit

- `_ShowNotesWorker.stop` joins for 5 seconds then clears singleton even if its daemon worker remains alive. On lifecycle restart in the same Python process this can create **two active workers against the same queue**. Audit/fence worker lifetime and add a deterministic blocked-worker stop/restart regression. Do not force-stop in-flight operations, but do not spawn a duplicate worker.
- Keep current single-process documented assumption and no unauthenticated admin/mutation endpoints. Queue GET may expose only counts.
- Preserve parent URL result, direct playlist full-ingest behavior, playlist child link-only behavior, issue #15 block cooldown, local-transcribe queue-first contract, `references.md` and archive data. Never introduce real provider calls in tests.

## Deliverables and acceptance

1. Before local repo work, verify an external WIP marker; preserve unrelated checkout changes, use isolated worktree. Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, canonical pointer/handoff, this task, PR #19 diff, production incident issue #18.
2. Add **fail-before / pass-after deterministic regressions** for each blocking defect and lifecycle guard. No testing against the production archive, no real network I/O. Keep the original 355 passing tests.
3. Implement smallest reliable correction; update README and API/queue documentation. Explain how parent requests are protected from **slow background work**, what still can legitimately take time in the explicit parent processing path, and how queue errors/backpressure are exposed.
4. Run full `python -m pytest -q`, `python -m compileall -q src get_transcript.py`, `git diff --check` and any targeted race/restart tests. Preserve valid existing API response statuses; don't bump the client timeout as a substitute.
5. Update `.codex/notes/current-task.md` and `.codex/notes/agent-handoff.md` with actual evidence, risks, changes and exactly **one** recommended next action; mark old issue #18 original task as code in-review (not QA-approved).
6. Commit and push **only** `fix/issue-18-youtube-show-notes-timeout`; update existing **draft PR #19**, never merge or deploy. Verify GitHub PR CI successful on exact remote final SHA; the workflow does not currently promise branch-push CI for this branch.
7. Return `[REVIEW-REQUEST]` with exact new SHA, PR/CI URLs, measured deterministic race results, file scope, known limitations. Architect reviews independently.

**Strictly prohibited without separate authorization:** push/merge to `main`, production pipx install/restart, live video ingestion, archive mutation/restore, access to `~/.ssh` private keys or secrets. Existing issue #15 rollout approval does NOT authorize #18 deployment.

## Exactly one next step

OpenCode: implement these narrow QA corrections in existing branch and draft PR #19, then request independent review.
