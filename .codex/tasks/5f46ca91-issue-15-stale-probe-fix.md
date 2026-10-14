# [fix] Issue #15 QA correction 2: stale probe failure and fail-safe state

- Task ID: 5f46ca91
- State: CORRECTION QUEUED / PR #16 NOT ACCEPTED
- Repository: https://github.com/draeician/ref
- Branch: `fix/issue-15-ref-api-disconnect`
- Pull request: https://github.com/draeician/ref/pull/16 (keep draft, do not merge)
- Independently reviewed implementation SHA: `669c692d4b98526cb86167a679be8acdf7cd2b33`
- Baseline default `main` SHA: `276ea2afdfd8ea401f1849ba50b847225487f9ee`
- Prior issue task: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`
- Previous correction: `.codex/tasks/e6c9124b-issue-15-probe-ownership-correction.md`
- Canonical pointer: `.codex/notes/current-task.md`
- Handoff: `.codex/notes/agent-handoff.md`

## Independent review results and why this is blocking

Both exact-SHA GitHub Actions jobs succeeded (push 38586292021 and PR 38586301572, **326 passed** each). The previous pre-download probe-lock bug and stale SUCCESS-clear bug were fixed, real multi-process single-flight tests were added, PR description properly distinguishes the unresolved service-stop disconnect from the transcript cooldown. Branch discipline intact, no production changes.

Three small residual defects remain in `src/ref_cli/transcript_block.py`:

1. **Stale unrelated FAIL result can seize a newer probe's lease**: `finish_probe` lines 552–556 unconditionally sets `marker['lease_owner']=None`, `lease_expires_at=0`, `next_probe_at=now+60`, without checking `decision.owner` and `decision.epoch_blocked_until`. Repro sequence using injected `now`: enter expired cooldown; A claims probe at T0 (lease expires T0+300); B claims *new* lease at T0+301; A finishes with unrelated failure at T0+302. A incorrectly removes B's lease. After backoff C can claim while B still active. Similarly, an old unrelated failure can perturb an unrelated/newer block epoch. Only the current owner and matching epoch may release the lease or set backoff. Stale finishes should leave the entire newer marker untouched.
2. **Numeric-overflow marker parse**: `_as_finite_nonneg` lines 157–165 catches TypeError/ValueError but not OverflowError. A valid JSON marker with e.g. a 400-digit integer for `blocked_until` (or `set_at`, `lease_expires_at`, `next_probe_at`) can raise `OverflowError` from `float(huge_int)`; this violates "corrupt marker never aborts capture". Extend defensive conversion appropriately and add deterministic coverage. No need to invent a new parser.
3. **Missing in-process synchronization when file locking is unavailable**: `_file_lock` lines 216–245 yields *without a lock* when `fcntl` import, archive directory creation, lock-file open or `flock` fails. Yet the documented fallback promises single-flight within the process. `_memory_state_lock` protects individual get/set only, not the entire marker read/claim/write. Two threads can both claim the same recovery probe in this fallback mode. Add a short **process-local state RLock** around marker read/modify/write in `_file_lock` even if POSIX locking fails, and deterministic threaded regression with forced lock unavailability and marker write failure. Do not hold locks over provider I/O or add a new scheduler/queue.

## Scope

Modify only:
- `src/ref_cli/transcript_block.py` (the guard/parsing/local lock repairs);
- `tests/test_transcript_probe_concurrency.py` (new deterministic fail-before-fix regressions);
- `tests/test_transcript_block.py` only if needed;
- `.codex/notes/current-task.md`, `.codex/notes/agent-handoff.md` and PR #16 metadata/handoff.

Prefer a short, targeted repair. Preserve existing cooldown duration/configuration, cross-process marker/lock interface and bounded lease, queue-first local-transcribe semantics, pending-file fallback, API schema, metadata and show-notes, 50-link cap, no auth weakening.

Important safety invariants: ordinary successful provider requests must never clear a newer block; stale failure/abort must never overwrite a newer owner/epoch; current owner's unrelated failure releases only its own lease and schedules a bounded backoff; confirmed IP block takes precedence and does not extend an active cooldown; marker parse is fail-safe without aborting capture.

## Acceptance tests (must actually run)

1. Deterministic `now` test with A probe, B reclaim after A expires, then A unrelated fail: verify B's token and lease expiry are unchanged; C is denied while B owns it. After B's own unrelated failure, verify backoff then recovery. Also check stale failure after a new block epoch cannot edit its state.
2. Valid JSON with huge 400-digit numbers in each timestamp key: `read_marker`/`is_blocked`/`begin_probe` do not raise. Existing malformed-marker test suite passes.
3. Force a failure to acquire file lock (e.g. mock `fcntl.flock`/lock path) and marker write, while two threads start together: assert exactly one process-local recovery owner; the other is denied. Use event/barrier coordination instead of a sleep-only race when possible. Ensure capture still queues on block.
4. Demonstrate at least new regressions fail against reviewed SHA and pass after fix. Run focused pytest plus full `python3 -m pytest -q`, `python3 -m compileall -q src get_transcript.py`, `git diff --check`.
5. Push to SAME development branch, update SAME draft PR #16. Verify both GitHub Actions workflows completed successfully on exact new final remote SHA. No merge/deploy/restart.
6. Update the canonical handoff with changed areas, regression evidence, commands/results, true final SHA, remaining risks and **exactly one next step**. PR title currently says “ref-api disconnect hardening” while no shutdown code changed; re-title to emphasize the actual transcript cooldown, e.g. `[fix] Issue #15: YouTube transcript IP-block cooldown`. Retain evidence of observed shutdown in PR body and explicitly state production validation/open cutover gate.

## Out of scope

- New job scheduler, external coordination service, redis/distributed lock, proxy rotation.
- Full redesign of synchronous `POST /urls` or systemd shutdown path.
- Production installation, service restart, live cutover or `main` merge (require user authorization).
- Unrelated lint/packaging or security refactors.

## Exactly one next action

OpenCode should implement this correction on the current branch/PR, update handoff, push and verify exact-SHA remote CI, and post a new `[REVIEW-REQUEST]`.
