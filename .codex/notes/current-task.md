# Current task — ref-cli

- **State:** INDEPENDENT QA FAILED on corrected PR #16 head `669c692d4b98526cb86167a679be8acdf7cd2b33`; second **narrow corrective task QUEUED**. The original issue is not completed or accepted.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`. No merge/deployment. Default branch `main` baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Canonical current task:** [5f46ca91 — stale probe failure + fail-safe marker/local-lock correction](../tasks/5f46ca91-issue-15-stale-probe-fix.md).
- **Prior correction:** [e6c9124b — cross-process single-flight and honest disconnect claims](../tasks/e6c9124b-issue-15-probe-ownership-correction.md) (implemented, prior races repaired, but additional QA defects found).
- **Original issue specification:** [b3e718cf](../tasks/b3e718cf-issue-15-ref-api-disconnect.md).
- **Draft PR:** https://github.com/draeician/ref/pull/16 (update same PR and branch).
- **Issue:** https://github.com/draeician/ref/issues/15
- **Canonical handoff:** [agent-handoff.md](agent-handoff.md).

## Verified positive gates on reviewed implementation

GitHub Actions push `38586292021` and pull request `38586301572` both ran on exact reviewed SHA `669c692d4b98526cb86167a679be8acdf7cd2b33`; each completed SUCCESS with 326 passing tests. CI is necessary but not sufficient: targeted code review identified untested races. Cross-process first lease ownership, stale SUCCESS protection, and pre-legacy cooldown guard have passed source-level review. The patch does not fix systemd stop-in-flight `RemoteDisconnected`; live production validation remains open as a separate user-authorized cutover gate.

## Blocking QA defects

- Stale unrelated FAILURE/abort in `finish_probe` can overwrite another live lease / a newer epoch (owner/epoch guard missing on non-block failure path).
- Numeric conversion of valid-JSON huge ints can raise OverflowError during marker parsing.
- No process-local critical section if `fcntl`/file lock is unavailable; process-local fallback promise can be violated by threads.

## Recovery and quality gate

Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, this pointer, current corrective task and handoff. Preserve WIP; use existing isolated worktree, fetch latest branch; test fail-before-fix, implement tiny correction, run focused/full pytest and compileall, update handoff and existing PR, push only development branch, verify BOTH required GitHub Actions on exact final SHA. Do not merge or deploy. Await independent re-review.
