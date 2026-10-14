# Current task — ref-cli

- **State:** **INDEPENDENT CODE QA PASSED** for issue #15 cooldown and probe corrections at exact reviewed commit `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`; **NOT MERGED OR DEPLOYED**. Production/cutover gate remains OPEN.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`; protected default branch `main` baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Canonical current task:** [a92d761e — main-branch CI + read-only cutover preflight](../tasks/a92d761e-issue-15-cutover-preflight.md), queued after QA.
- **Completed code/correction tasks (review accepted, merge still pending):** [b3e718cf — issue #15 cooldown/incident](../tasks/b3e718cf-issue-15-ref-api-disconnect.md), [e6c9124b — recovery probe ownership](../tasks/e6c9124b-issue-15-probe-ownership-correction.md), [5f46ca91 — stale failure/local-state correction](../tasks/5f46ca91-issue-15-stale-probe-fix.md).
- **Draft PR:** https://github.com/draeician/ref/pull/16 (do not merge or deploy without explicit user authorization).
- **Issue:** https://github.com/draeician/ref/issues/15
- **Canonical handoff:** [agent-handoff.md](agent-handoff.md).

## Independent QA evidence and architectural decisions

- Reviewed actual `src/ref_cli/transcript_block.py`, `src/ref_cli/cli.py`, deterministic threaded/OS-process concurrency tests, existing blocked-transcript/API tests, README, workflow, and PR diff on exact SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`.
- Required GitHub Actions **push** https://github.com/draeician/ref/actions/runs/38619727048 and **PR** https://github.com/draeician/ref/actions/runs/38619733660 completed SUCCESS on exact reviewed SHA; direct job logs each confirm **336 passed, 1 warning**.
- Previous stale-failure lease overwrite, huge-integer parser exception, and no-file-lock thread races were fixed and covered with fail-before-fix regressions. No unexplained file changes or committed WIP artefacts.
- Transcript cooldown reduces banned transcript calls and preserves local-transcribe queue-first fallback. It **does NOT** fix disconnects from an operator stopping the synchronous API service mid-request. No live deployment/validation was authorized or performed.
- **Cutover CI gap identified:** current workflow triggers pushes only to feature branch, not `main`; a post-merge main-SHA CI gate cannot run until this is amended. Next task is scoped to this workflow trigger plus read-only preflight. Keep application code frozen pending release.
- Code review acceptance is *not* issue closure, merged-main CI, or production acceptance; all latter gates remain separately open.

## Recovery / next actor

Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, this pointer, the new current task, handoff, `README.md`, `src/ref_cli/server_install.py`, and other links named by the task. Check local WIP/git status, use the same isolated branch/worktree, and do not touch production except read-only inspection. After implementation: full tests and compile, push on development branch, verify exact-SHA push + PR workflows, update handoff and request independent re-review. **Never merge, install, restart or deploy without explicit user approval.**
