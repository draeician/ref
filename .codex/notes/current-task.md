# Current task — ref-cli

- **State:** INDEPENDENT QA FAILED on corrected PR #16 head `669c692d4b98526cb86167a679be8acdf7cd2b33`; **third narrow corrective task IMPLEMENTED on same branch/PR — awaiting independent re-review**. The original issue is not completed or accepted. Not merged/deployed.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`. Default branch `main` baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Current corrective task:** [5f46ca91 — stale probe failure + fail-safe marker/local-lock correction](../tasks/5f46ca91-issue-15-stale-probe-fix.md) (implemented).
- **Prior correction:** [e6c9124b — cross-process single-flight and honest disconnect claims](../tasks/e6c9124b-issue-15-probe-ownership-correction.md).
- **Original issue specification:** [b3e718cf](../tasks/b3e718cf-issue-15-ref-api-disconnect.md).
- **Draft PR:** https://github.com/draeician/ref/pull/16 (update same PR and branch; title corrected to not imply the HTTP disconnect was fixed).
- **Issue:** https://github.com/draeician/ref/issues/15
- **Canonical handoff:** [agent-handoff.md](agent-handoff.md).

## Correction implemented (implementer's turn, not yet independently re-reviewed)
- Stale unrelated FAILURE/abort (and stale success) from an older probe can no longer seize another owner's lease, overwrite a newer block epoch, or arm a backoff on someone else's behalf — `finish_probe` validates `lease_owner == decision.owner` and `blocked_until == decision.epoch_blocked_until` before mutating any marker state.
- Marker parsing catches `OverflowError` for huge-but-valid JSON integers on every timestamp field (and NaN/inf and type garbage) — a corrupt or extreme marker can never abort API capture.
- `_file_lock` now enforces a process-local `RLock` critical section for marker read/modify/write even when POSIX `flock`/lock-file/archive access is unavailable, so single-flight ownership holds at thread level; never held across provider I/O.

## Quality gate
- New deterministic regressions (stale-fail ownership/epoch, huge-number parse, forced no-lock + no-persistence single-flight) demonstrated FAIL at reviewed SHA `669c692` and pass after the fix; focused/full pytest and compileall green. New remote SHA must have both push and PR GitHub Actions green; then independent re-review. Production stop/restart validation remains unapproved and open.

## Next actor
Architect: independently re-review corrected draft PR #16; do not merge/deploy until user-authorized cutover plus live stop-in-flight validation.
