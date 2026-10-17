# [fix] Issue #18 — final queue time validation and worker shutdown fence

- **Task ID:** 9b62e0c4
- **State:** IMPLEMENTED — both narrow release blockers corrected on draft PR #19; awaiting independent architect QA (no merge/deploy).
- **PR:** https://github.com/draeician/ref/pull/19 (SAME draft PR; no new PR/branch)
- **Branch:** `fix/issue-18-youtube-show-notes-timeout`
- **Reviewed application SHA:** `586ef80ddd57174449ddb04e2239de4470811639`
- **Reviewed PR head SHA:** `3ea816272c71723d4c16b494c3a7bf1411118812`
- **Main baseline:** `799b10f28dd3776a8d9904509d166368e289bb7c` (no merge).
- **CI:** https://github.com/draeician/ref/actions/runs/39002061973 — independently verified SUCCESS, exact reviewed SHA, actual pytest log **372 passed, 1 warning in 10.68s**.
- **Prior canonical tasks:** `d0c54a91`, `7e4c9b12`, `4f29b6c1`. The previous three P0/P1 issues are **resolved on code review**: real whole-file archive rewrites use shared `archive_lock`, malformed typical queue records fail closed, and timed-out stop/restart can hand off worker.
- **Verdict:** CHANGES REQUIRED solely for two remaining correctness gaps; no merge or production deployment authorized.

## Finding 1 — Non-finite persisted timestamps silently strand queue jobs

`src/ref_api/show_notes_queue.py:_normalize_job` `_ts()` accepts any int/float and returns `float(value)` without `math.isfinite` or an explicit range requirement. Python `json.loads` accepts `NaN`, `Infinity`, and also `1e309` as infinite float; all are parseable but **not valid queue deadlines**. For example:

```json
{"jobs":{"j1":{"id":"j1","url":"https://example.org/a","kind":"ingest","status":"pending","attempts":0,"next_attempt_at":NaN}}}
```

`_load` accepts this existing file as healthy, so `next_pending` computes `NaN <= now` = false. The accepted `pending` job silently waits **forever** rather than being processed or flagging corruption. Infinite values can similarly strand jobs or poison retention ordering. A persisted file with huge-but-valid JSON timestamp (`1e309`) is another deterministic repro.

**Required:** Reject non-finite timestamps and other illegal deadline ranges while parsing existing queues, `QueueCorruptError` fail-closed, do not overwrite the original bytes. Ensure generated writes use finite timestamps. Add `pytest.mark.parametrize` regression fixtures for `NaN`, `Infinity`, `-Infinity`, `1e309` and explicit valid timestamps; after `is_corrupt()`, attempted `enqueue/recover` must raise and original file remain byte-for-byte identical. Avoid a merely cosmetic validation check.

## Finding 2 — Pending restart is not canceled by a subsequent shutdown

`src/ref_api/service.py` uses `_restart_pending` and `_worker_exited` for safe successor handoff. Scenario:

1. A worker is held inside slow child `process_url` by a `threading.Event`.
2. `stop_show_notes_worker` times out, leaving old worker with stop flag set.
3. `start_show_notes_worker` is called for an in-process lifespan restart while old worker remains alive, setting `_restart_pending=True`.
4. **That new lifespan is stopped again** before slow child completes: `stop_show_notes_worker` invokes `worker.stop()` but does not clear `_restart_pending`.
5. When old child finally returns, `_worker_exited` still sees `_restart_pending=True` and **spawns a new worker even though no lifespan is active**. It may drain queue jobs after a requested shutdown.

**Required:** Cancel any pending restart when the latest stop/shutdown is requested (subject to worker identity/generation fencing). Guarantee no post-shutdown successor, no overlapping draining workers, and successful handoff only when a *currently active* lifespan has requested restart. Add deterministic Event regression for stop→start→stop→release (NO successor; queued job remains persisted); preserve existing stop→start→release case (successor drains). Avoid blocking forever on an active slow provider and preserve existing service lifecycle API.

## Scope and delivery

- Keep all previously accepted changes: fast parent HTTP response, durable queued discovery/ingest, direct vs discovered playlist policy, complete archive write locking without long provider locks, lossless fail-closed queue storage, bounded history/retries, issue #15 cooldown and local-transcribe fallback.
- No new API surface, archive format migration or systemd unit changes needed.
- Use external WIP marker, isolated worktree, preserve unrelated checkout state, no `~/.ssh` keys/secrets inspection. No live test URL ingest, modifications to user's `~/references`, pipx install, service restart or direct `main` push.
- On SAME branch/PR, write deterministic fail-before/pass-after regressions; run `python -m pytest -q`, `python -m compileall -q src tests get_transcript.py`, `git diff --check`; record honest results. Update this task and canonical `.codex/notes/current-task.md` / `.codex/notes/agent-handoff.md`; update README if behavior changes.
- Commit/push only `fix/issue-18-youtube-show-notes-timeout`; verify exact-final-SHA PR CI success. Report `[REVIEW-REQUEST]` with SHA, CI, focused test results, changed-file scope and remaining limitations. Do not mark ready/merge or deploy without independent architect QA and fresh user approval.

## Exactly one next step

OpenCode: implement these two narrow corrections on existing draft PR #19 and return an exact-final-SHA `[REVIEW-REQUEST]`.

## Implementation (OpenCode, 2026-10-17)

Both findings corrected on `fix/issue-18-youtube-show-notes-timeout`; draft PR #19 updated (no new PR/branch, no main merge).

- **Finding 1** — `src/ref_api/show_notes_queue.py`: `_normalize_job._ts` now rejects any non-finite value via `math.isfinite` (NaN, Infinity, -Infinity, and `1e309` which `json.loads` parses as `inf`), raising `ValueError` inside the existing fail-closed `_load` boundary → queue marked corrupt, original `jobs.json` bytes preserved, `enqueue`/`recover` raise `QueueCorruptError`. Generated writes already use finite `time.time()`/bounded retry delays, so no writer change was needed.
- **Finding 2** — `src/ref_api/service.py`: `stop_show_notes_worker` now clears `_restart_pending` (under `_worker_lock`, alongside the identity read) so a second shutdown cancels a pending successor handoff; the draining worker's `_worker_exited` clears the singleton instead of spawning a successor. Worker identity/generation fencing is unchanged (`_worker_exited` still checks `_worker is worker`). The existing stop→start→release successor-handoff path is preserved.

### Regression evidence (fail-before → pass-after)
- New `tests/test_show_notes_queue.py`: 12 non-finite fixtures (`NaN`/`Infinity`/`-Infinity`/`1e309` × `next_attempt_at`/`enqueued_at`/`updated_at`) + 4 finite-timestamp loads-clean fixtures. All 12 non-finite cases FAIL when the `math.isfinite` guard is removed (queue not corrupt), PASS after.
- New `tests/test_show_notes_worker.py::test_second_stop_cancels_pending_restart`: stop→start→stop→release asserts no successor (`_worker is None`, zero worker threads, queued job stays pending). FAILS when `_restart_pending = False` is removed from `stop_show_notes_worker`; PASSES after. Existing `test_worker_resumes_after_timed_out_stop_and_restart` (successor drains) still passes.

### Checks (local, Python 3.12.3)
- `python -m pytest -q` → **389 passed, 1 warning** (372 prior + 17 new).
- `python -m compileall -q src tests get_transcript.py` → OK.
- `git diff --check` → clean.

### Commits
- `bdd2916` `[fix] Reject non-finite queue timestamps; cancel pending worker restart on stop` (application + tests).
- Follow-up `[docs]` commit records this task/current-task/handoff.

