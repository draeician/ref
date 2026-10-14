# [ci] Issue #15 merge readiness and read-only cutover preflight

- Task ID: a92d761e
- State: CI / read-only preflight evidence verified on exact SHA `5747ff15aaaad1df998c3dae750d5f82bb24d090`, but release-plan QA **FAILED**: pre-API rollback target `ref-cli==1.6.11` is unsafe; unverified pipx extras preservation and blanket archive restore present data/service risks. Narrow successor correction: `.codex/tasks/c41e90b7-issue-15-pipx-cutover-safety.md`. No merge/deploy authorized.
- Priority: High — release/cutover gate
- Current development branch: `fix/issue-15-ref-api-disconnect`
- Draft PR: https://github.com/draeician/ref/pull/16
- Default branch: `main` (protected; do not push directly)
- QA-accepted implementation SHA: `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`
- Prior tasks: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`, `.codex/tasks/e6c9124b-issue-15-probe-ownership-correction.md`, `.codex/tasks/5f46ca91-issue-15-stale-probe-fix.md`.
- Canonical status/handoff: `.codex/notes/current-task.md`, `.codex/notes/agent-handoff.md`.

## Why now

Independent architect review accepted the cooldown implementation and all corrections at exact head `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`. Exact-SHA push CI run `38619727048` and PR CI run `38619733660` both succeeded with `336 passed, 1 warning`. PR is still draft; `main` remained at `276ea2afdfd8ea401f1849ba50b847225487f9ee`.

**Release gate gap**: `.github/workflows/tests.yml` only triggers on push to `fix/issue-15-ref-api-disconnect` and on pull requests. It does **not** trigger on a push to `main`. Project's post-merge exact-main-SHA CI requirement therefore cannot be verified until the workflow is fixed. This is **not** a defect in the approved cooldown logic; keep separate.

The observed `RemoteDisconnected` was a reported systemd stop/SIGKILL during synchronous in-flight API ingest. This feature does not make stopping an active request safe; live production validation and shutdown policy remain separate, permission-gated.

## Required work

1. **CI trigger only:** On the existing PR development branch, edit `.github/workflows/tests.yml` to include `main` alongside the established feature branch in `on.push.branches`. Preserve the PR trigger, Python 3.12, pytest install/test steps; don't introduce a separate workflow, token, privileged job or unconfigured gate. Avoid changing application code/tests unless a clearly justified CI problem emerges. Document why `main` push CI is needed.
2. **Read-only cutover preflight:** Read `src/ref_cli/server_install.py`, `src/ref_api/server.py`, `src/ref_api/service.py`, `src/ref_cli/api_client.py`, `README.md`, and systemd user unit provisioning templates. On `minion` use only harmless observational commands (status, `systemctl --user show/cat`, `journalctl --user` bounded, `pipx list`, `ref --version`, `ref --status`, `git status`, filesystem free space as useful), sanitized to exclude secrets and private archive contents. Do **not** attempt any live YouTube URL ingestion, install/upgrade, restart, systemd unit modification, disable, merge or production change.
3. **Cutover plan in canonical handoff:** State the **actual** package install provenance and pipx procedure (do not assume `pipx upgrade` fetches unreleased GitHub code), snapshot/backup verification plan for `references.md`, safe operator-chosen idle-window sequencing, expected commit/version after authorized merge/deploy, concrete `/health` and `ref --status` checks, cooldown marker behavior, timeouts/long synchronous fanout caveat, rollback commands scoped to actual installed deployment, and ownership of each gate. Do not paste secrets, complete journals, or large logs.
4. **Explicit authorization boundary:** `main` merge, making PR ready-for-review (optional), production package changes, any ref-api stop/restart, and live validation are **on hold** pending user approval. The architect will verify the exact PR head and required CI, request explicit merge authorization, independently verify merged main SHA/post-merge CI, then separately coordinate operator-authorized deployment and live validation. No one may infer authorization from this task.
5. **Update repo handoff/status:** Preserve QA PASS on code SHA above; make new release-preflight task active until complete. Record findings, changed files, CI links, risks, and **exactly one recommended next step**.

## Acceptance gates

- Changed application files: **none**, unless justified and separately reviewed. Existing test workflow updated to run on PRs and pushes to both `main` and the feature branch.
- `python3 -m pytest -q` passes; `python3 -m compileall -q src get_transcript.py` passes; `git diff --check` clean.
- Push and PR GitHub Actions completed SUCCESS on **exact new final remote branch SHA** and include the intended workflow configuration.
- README/current-task/handoff reflect actual release gate and production preflight without claiming the unmodified shutdown behavior is resolved.
- No secrets or archive data exposed; no WIP or local-only file committed; no main push/merge/service action/deployment.
- Final message contains draft PR, final SHA, exact-SHA CI links, read-only preflight result and blocker/authorization boundary.

## Exactly one next step

OpenCode: safely fetch latest `fix/issue-15-ref-api-disconnect`, implement only the main-push CI trigger and perform read-only cutover preflight, update the existing canonical handoff, push the same branch/PR, and submit `[REVIEW-REQUEST]` with exact new SHA and both passing remote workflows.
