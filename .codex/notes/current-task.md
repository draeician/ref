# Current task — ref-cli

- **State:** Issue #18 draft PR #19 **FINAL ARCHITECT QA REQUIRES TWO NARROW CORRECTIONS**; do not merge/deploy. Previous second-QA P0 archive integrity, P0 typical queue corruption, and P1 worker restart findings are **source-review accepted** at code SHA `586ef80ddd57174449ddb04e2239de4470811639`, final reviewed PR SHA `3ea816272c71723d4c16b494c3a7bf1411118812`. The current outstanding findings concern non-finite persisted queue deadlines and cancellation of a pending worker restart after another shutdown.
- **ACTIVE canonical corrective task:** [9b62e0c4 — queue timestamp validation and shutdown fence](../tasks/9b62e0c4-issue-18-final-queue-lifecycle-qa.md) (OPEN).
- **Prior tasks:** [4f29b6c1](../tasks/4f29b6c1-issue-18-qa-archive-persistence-lifecycle.md) (corrected/reviewed), [7e4c9b12](../tasks/7e4c9b12-issue-18-qa-corrections.md), [d0c54a91](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development:** `fix/issue-18-youtube-show-notes-timeout`, existing [draft PR #19](https://github.com/draeician/ref/pull/19), base `main` at `799b10f28dd3776a8d9904509d166368e289bb7c`. No merge.
- **Handoff:** [agent-handoff.md](agent-handoff.md).

## Independent verification of 4f29b6c1 corrections

- PR/dev head independently verified `3ea816272c71723d4c16b494c3a7bf1411118812`; application code `586ef80ddd57174449ddb04e2239de4470811639`. Exact GitHub Actions PR run https://github.com/draeician/ref/actions/runs/39002061973 SUCCESS; job log **372 passed, 1 warning in 10.68s**. OpenCode reports local compileall and diff-check, not independently executed by architect.
- **Previous blocker A resolved:** `src/ref_cli/archive_lock.py` shared process-local `RLock`; enrichment gather+whole-file rewrite now under same lock as append and `update_reference_entry`; `update_transcript` fetches provider outside lock, re-reads/commits under it. Deterministic archive-rewrite/append regression inspects actual archive file.
- **Previous blocker B resolved:** `ShowNotesQueue._load` no longer marks healthy before validation and catches malformed JSON/UTF-8/type conversions into corrupt read-only state; regression asserts byte retention.
- **Previous blocker C resolved for stop→start:** old worker's exit hands off to a successor when pending restart is set; new regression verifies pending jobs resume without simultaneous drain.
- **New narrow blocker 1:** parseable `NaN`/`Infinity` values in persisted `next_attempt_at` are accepted as valid and can strand queued work forever. `_ts` must reject non-finite numbers, fail closed, preserve original bytes, and gain deterministic tests.
- **New narrow blocker 2:** worker `_restart_pending` remains set after a *second* stop request. stop→start→stop→release can spawn a successor after the latest shutdown, causing archive work after service shutdown. Cancel pending restart on stop and test both lifecycle sequences.
- Production still runs the previous issue #15 release and #18 has not been approved for rollout.

## Authorization

OpenCode may implement/code-test on isolated branch and update existing draft PR #19; no direct push to main, production pipx/service/archive mutation, live ingest or secret inspection. Issue #15 deployment authorization does not apply to issue #18.

## Exactly one next step

OpenCode: execute task `9b62e0c4`, run full checks and exact-final-SHA PR CI, then return `[REVIEW-REQUEST]` for independent architect QA.
