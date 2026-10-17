# Current task — ref-cli

- **State:** Issue #18 draft PR #19 **two narrow corrections IMPLEMENTED, awaiting independent architect QA**; do not merge/deploy. Both final-QA findings are corrected on the branch: (1) non-finite persisted queue timestamps (`NaN`/`Infinity`/`-Infinity`/`1e309`) now fail closed via `math.isfinite`; (2) `stop_show_notes_worker` cancels a pending worker restart so a second shutdown cannot resurrect the worker. Previous second-QA P0 archive integrity, P0 typical queue corruption, and P1 worker restart findings remain source-review accepted.
- **ACTIVE canonical corrective task:** [9b62e0c4 — queue timestamp validation and shutdown fence](../tasks/9b62e0c4-issue-18-final-queue-lifecycle-qa.md) (IMPLEMENTED; awaiting independent QA).
- **Prior tasks:** [4f29b6c1](../tasks/4f29b6c1-issue-18-qa-archive-persistence-lifecycle.md) (corrected/reviewed), [7e4c9b12](../tasks/7e4c9b12-issue-18-qa-corrections.md), [d0c54a91](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development:** `fix/issue-18-youtube-show-notes-timeout`, existing [draft PR #19](https://github.com/draeician/ref/pull/19), base `main` at `799b10f28dd3776a8d9904509d166368e289bb7c`. No merge.
- **Handoff:** [agent-handoff.md](agent-handoff.md).

## Implementation of 9b62e0c4 corrections

- **Finding 1 (non-finite timestamps):** `ShowNotesQueue._normalize_job._ts` rejects non-finite values via `math.isfinite` (NaN/Infinity/-Infinity/`1e309`→`inf`), fail-closed, original `jobs.json` bytes preserved. Generated writes already use finite `time.time()`/bounded delays.
- **Finding 2 (pending restart cancel):** `stop_show_notes_worker` clears `_restart_pending` under `_worker_lock`; a second shutdown cancels the successor handoff. Existing stop→start→release successor handoff preserved.
- **Fail-before/pass-after verified:** 12 non-finite timestamp fixtures + `test_second_stop_cancels_pending_restart` FAIL without the guards, PASS after.
- **Checks (local, Python 3.12.3):** `pytest -q` → **389 passed, 1 warning** (372 prior + 17 new); `compileall -q src tests get_transcript.py` OK; `git diff --check` clean.
- Production still runs the previous issue #15 release; #18 has not been approved for rollout.

## Authorization

OpenCode may implement/code-test on isolated branch and update existing draft PR #19; no direct push to main, production pipx/service/archive mutation, live ingest or secret inspection. Issue #15 deployment authorization does not apply to issue #18.

## Exactly one next step

OpenCode: push the two corrections, update draft PR #19, verify exact-final-SHA PR CI, then return `[REVIEW-REQUEST]` for independent architect QA.
