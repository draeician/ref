# Current task — ref-cli

- **State:** **CUTOVER PREFLIGHT COMPLETE** for issue #15: independent code QA already PASSED at `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`; CI trigger now also fires on pushes to `main`; read-only minion preflight done. **NOT MERGED OR DEPLOYED**; main merge, PR ready-for-review, package install/upgrade, service restart, and live validation remain explicitly authorization-gated and OPEN.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`; protected default branch `main` baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Canonical current task:** [a92d761e — main-branch CI + read-only cutover preflight](../tasks/a92d761e-issue-15-cutover-preflight.md), now ACTIVE/complete pending independent verification.
- **Completed code/correction tasks (review accepted, merge still pending):** [b3e718cf — issue #15 cooldown/incident](../tasks/b3e718cf-issue-15-ref-api-disconnect.md), [e6c9124b — recovery probe ownership](../tasks/e6c9124b-issue-15-probe-ownership-correction.md), [5f46ca91 — stale failure/local-state correction](../tasks/5f46ca91-issue-15-stale-probe-fix.md).
- **Draft PR:** https://github.com/draeician/ref/pull/16 (do not merge or deploy without explicit user authorization).
- **Issue:** https://github.com/draeician/ref/issues/15
- **Canonical handoff:** [agent-handoff.md](agent-handoff.md).

## Independent QA evidence and architectural decisions

- Reviewed actual `src/ref_cli/transcript_block.py`, `src/ref_cli/cli.py`, deterministic threaded/OS-process concurrency tests, existing blocked-transcript/API tests, README, workflow, and PR diff on exact SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`.
- Required GitHub Actions **push** https://github.com/draeician/ref/actions/runs/38619727048 and **PR** https://github.com/draeician/ref/actions/runs/38619733660 completed SUCCESS on exact reviewed SHA; direct job logs each confirm **336 passed, 1 warning**.
- Previous stale-failure lease overwrite, huge-integer parser exception, and no-file-lock thread races were fixed and covered with fail-before-fix regressions. No unexplained file changes or committed WIP artefacts.
- Transcript cooldown reduces banned transcript calls and preserves local-transcribe queue-first fallback. It **does NOT** fix disconnects from an operator stopping the synchronous API service mid-request. No live deployment/validation was authorized or performed.
- **Cutover CI gap CLOSED:** `.github/workflows/tests.yml` now also runs on pushes to `main` (PR + feature-branch triggers preserved) so the post-merge exact-default-branch-SHA gate can run.
- **Read-only preflight (2026-10-14, minion):** service active/running 17h, unit has no `TimeoutStopSec` override (effective 90s), installed `ref-cli 1.6.12b1.dev40+g276ea2afd.d20261010` is a **non-editable local-dir pipx install** (`file:///opt/md2/git/personal/ref`), `/health` ok on that old build, `~/references` (638M) has gzip snapshots and `references.md.bak-*.gz`, 3.6T free, cooldown marker absent pre-cutover. **`pipx upgrade` will NOT fetch the unreleased branch** — deployment must reinstall from the SHA-pinned source (procedure in handoff); rollback commands recorded. No install/restart/merge performed.
- Code review acceptance is *not* issue closure, merged-main CI, or production acceptance; all latter gates remain separately open.

## Recovery / next actor

Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, this pointer, the new current task, handoff, `README.md`, `src/ref_cli/server_install.py`, and other links named by the task. Check local WIP/git status, use the same isolated branch/worktree, and do not touch production except read-only inspection. Independent re-review of the preflight result and exact final remote SHA (push + PR workflows) is the next gate; after it, request explicit merge authorization from the user/architect. **Never merge, install, restart or deploy without explicit user approval.**
