# [fix] Issue #18 — second independent QA: archive consistency, queue validation, worker recovery

- **Task ID:** 4f29b6c1
- **State:** OPEN — 3 confirmed source-level blockers of issue #18 PR #19, awaiting OpenCode corrections and independent re-review.
- **Issue:** https://github.com/draeician/ref/issues/18
- **Existing draft PR:** https://github.com/draeician/ref/pull/19 — use this ONE PR, no new branch/PR.
- **Branch:** `fix/issue-18-youtube-show-notes-timeout`
- **Reviewed exact SHA:** `e83c468964db1e1cb600fb657cd446ab8bbcac99` (code `559767654a117dcc20564a3f4f39ab321476d20e`); `main` `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Exact-SHA GitHub PR CI:** https://github.com/draeician/ref/actions/runs/39000511326 — PASS, actual pytest job log **362 passed, 1 warning in 9.78s**. Passing tests do not establish race safety beyond tested cases.
- **Prior QA task:** `.codex/tasks/7e4c9b12-issue-18-qa-corrections.md`; original implementation task `.codex/tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md`.
- **Canonical notes:** `.codex/notes/current-task.md`, `.codex/notes/agent-handoff.md`.
- **Architect verdict:** CHANGES REQUIRED, NO MERGE/DEPLOY.

## Findings and required corrections

### P0 — Existing whole-archive enrichment rewrites bypass the new lock

`src/ref_api/service.py:261-265` now allows concurrent `ref_cli.process_url` calls without its former whole-operation `_write_lock` (correct for latency). `src/ref_cli/cli.py` introduces `_archive_lock` around append, specific check/write sections, and `update_reference_entry` read-modify-write. **But that is not the whole write surface**:

- `src/ref_cli/cli.py:update_reference_entry` calls `enrich_youtube_reference` **after leaving `_archive_lock`** (its network fetch must remain outside the lock).
- `src/ref_cli/enrichment.py:enrich_youtube_reference` gathers matching rows using `iter_data_rows(references_path)` and calls `references_format.apply_row_updates(references_path, ...)`.
- `src/ref_cli/references_format.py:apply_row_updates` directly reads and rewrites the **entire** `references.md` using `open(path,'r')` then `open(path,'w')`; no `_archive_lock` acquisition. `enrich_youtube_reference` also invokes this on unavailable/private video outcomes, which may delete entries.
- A concurrent API parent/child append or other archive rewrite can occur between `apply_row_updates`'s read and write and be silently overwritten. Concurrent line-number selection and whole-file rewriting can also apply stale updates to changed lines. This is directly in the newly permitted concurrency path, so it blocks merge.

**Required:** Audit EVERY refs read-modify-write/overwrite/deletion path invoked by concurrent API requests and workers, including `references_format.apply_row_updates`, unavailable-video cleanup, `update_transcript`, playlist/other item writes and enrichment. Use ONE shared archive lock for the entire *read/decide/write commit* section for each mutation, not for slow network/provider work. Architecturally avoid cyclic imports; if necessary factor the lock into a small shared module and update its consumers. Ensure backfill/direct CLI compatibility. Document any truly deferred direct CLI-vs-service process-lock limitations; do not falsely claim the process-local lock protects independent processes.

**Regression:** deterministic two-thread test using `threading.Event` to pause one rewrite between reading and committing, while another thread appends or rewrites a distinct row; assert BOTH survive with correct metadata, no dropped/duplicate rows. Test a realistic `enrich_youtube_reference` path, not only mocked `process_url` that does no actual archive mutations. Demonstrate fail-before/pass-after on reviewed implementation.

### P0 — Malformed queue job types can bypass fail-closed and cause overwrite

`src/ref_api/show_notes_queue.py:_load` sets `_loaded=True` **before validation**. `_valid_job` validates only map key, URL and status; `_normalize_job` then executes `int(job.get('attempts') or 0)` and other conversions without a guarded fail-closed boundary. Examples:

- Existing JSON `{"jobs":{"j1":{"id":"j1","url":"https://example.org/a","status":"pending","attempts":"bad"}}}` passes `_valid_job` then raises `ValueError` in `_normalize_job`.
- Unexpected types such as `"status":[]` can raise `TypeError` on membership in `ALLOWED_STATUSES`.
- Mismatching/missing inner `id`, strange `kind`/timestamps/attempt counts, and other required fields are not comprehensively validated; wrong inner ID can break terminal compaction.

In the first two cases, `_loaded` remains True but `_corrupt=False`; **the next `enqueue` skips revalidation and can overwrite the existing queue** via `_snapshot`, losing accepted jobs. This is the same data-loss class that the previous correction was meant to eliminate.

**Required:** Fully validate the schema and each field (types, ranges, kind/status, job ID consistency, timestamps, attempt values), and only set `_loaded` after successful completed validation or an explicit corrupt state; catch all parse/normalize/Unicode/IO failures and fail closed, preserving original file bytes. Never allow any exception path to leave the queue treated as fresh/healthy. Update `/queue` corrupt reporting. Test multiple malformed-but-parseable JSON fixtures, a failed initial load followed by `enqueue`, and assert no overwrite, no accepted-job loss, actionable error.

### P1 — Lifecycle fence prevents duplicates but can strand restarted worker

`src/ref_api/service.py:461-483`:

- `stop_show_notes_worker()` calls `worker.stop(timeout=5)`; if blocked worker is still alive, it retains `_worker` (good).
- The next `start_show_notes_worker()` sees this **alive but stop-signaled** worker and immediately returns without starting a successor.
- When the old worker finally completes its child, it exits. The newly started FastAPI lifespan then has **no active worker**, and queued jobs stop draining until another restart. The current test `test_worker_stop_fence_prevents_overlap` asserts there was only one thread and that old one exited, but never asserts the service resumes processing after restart.

**Required:** Ensure no two workers overlap AND successful restart restores continuous queue drain even when a prior worker was still draining at startup. Consider pending-restart handoff, worker generation fencing, or another explicit lifecycle protocol; no forced cancellation of in-flight provider I/O. Test Event-held worker, timed-out stop, new lifespan start, release old worker, then enqueue another job and assert that a worker processes it and the queue resumes. No overlapping workers at any time.

## Tests, constraints, and delivery

- Preserve confirmed previous fixes: parent HTTP response independent of metadata discovery + slow children; direct playlist expansion vs discovered playlist link-only behavior; durable job queue, bounded retries/compaction, terminal dedup; issue #15 persisted IP-block cooldown and local-transcribe queue-first fallback.
- Any additional findings from targeted archive-write audit should be corrected if on the concurrent API hot path; do not widen scope into unrelated performance redesign.
- Before working on minion local files: external WIP marker, `git status`, preserve unrelated WIP and production checkout; use the existing isolated worktree. No private SSH key inspection/secrets, no production ingest, pipx install, restarts or archive modifications.
- Add deterministic fail-before/pass-after tests and update the README, canonical task, handoff and current-task to reflect actual results and remaining limitations.
- Local gates: `python -m pytest -q`, `python -m compileall -q src tests` and `python -m compileall -q src get_transcript.py`, `git diff --check`; list exact results. Commit/push **only** existing `fix/issue-18-youtube-show-notes-timeout`; update same draft PR #19 and request exact-final-SHA PR CI green. PR workflow runs on pull requests; do not fabricate branch-push CI.
- Submit `[REVIEW-REQUEST]` with exact final remote SHA, PR link/CI URL, files changed, focused race evidence and full test counts, remaining risk. The architect decides merger only after independent re-review. No permission to merge or deploy issue #18 has been granted.

## Exactly one next step

OpenCode: implement the 3 corrective findings on existing draft PR #19 with deterministic fail-before/pass-after regressions; then request architect review on the exact new SHA.
