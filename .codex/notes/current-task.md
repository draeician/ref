# Current task — ref-cli

- **State:** Issue #15 transcript cooldown implementation QA PASSED at code SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`. Main-push CI trigger and read-only preflight were implemented at `5747ff15aaaad1df998c3dae750d5f82bb24d090`, with both exact-SHA workflows GREEN (336 tests each), BUT **release preflight QA FAILS pending narrow rollback/packaging correction**. Not merged/deployed.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`, protected default `main` remains `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Canonical current task:** [c41e90b7 — safe pipx cutover/rollback procedure](../tasks/c41e90b7-issue-15-pipx-cutover-safety.md).
- **Prior cutover-preflight task:** [a92d761e — main-push CI + read-only preflight](../tasks/a92d761e-issue-15-cutover-preflight.md) (CI completed, release instructions need correction).
- **Accepted code tasks:** [b3e718cf](../tasks/b3e718cf-issue-15-ref-api-disconnect.md), [e6c9124b](../tasks/e6c9124b-issue-15-probe-ownership-correction.md), [5f46ca91](../tasks/5f46ca91-issue-15-stale-probe-fix.md).
- **Draft PR:** https://github.com/draeician/ref/pull/16 (remain draft/unmerged until explicitly approved).
- **Handoff:** [agent-handoff.md](agent-handoff.md); GitHub issue https://github.com/draeician/ref/issues/15.

## Independent review of a92d761e

- Reviewed exact head `5747ff15aaaad1df998c3dae750d5f82bb24d090`, PR/base/branch state, actual `.github/workflows/tests.yml`, README, `pyproject.toml`, server install/API code, canonical documents, changed-file scope and direct push/PR logs.
- Required workflows SUCCESS at exact reviewed SHA: push https://github.com/draeician/ref/actions/runs/38635883999 and PR https://github.com/draeician/ref/actions/runs/38635892439, **336 passed** each.
- CI main-push trigger accepted; no application code changed. Read-only minion preflight evidence reported by OpenCode but not independently accessible to architect; no live mutation authorized.
- **FAIL: unsafe release plan.** PR body/handoff recommends `pipx install --force 'ref-cli==1.6.11'` as a rollback option, but README expressly identifies 1.6.11 as pre-API. Could remove `ref-api`. Original installation is API-capable at SHA `276ea2afd`; rollback must use that version. `pipx install --force` from VCS may not retain injected `[api]` extras, which requires isolated verification. Blindly restoring archive backup during code rollback risks discarding new entries. Full details/acceptance in task `c41e90b7`.
- The original shutdown-related `RemoteDisconnected` on systemd stop-in-flight remains distinct and uncorrected; production validation remains a separate authorization-gated cutover step.

## Next actor

OpenCode: preserve WIP, read this pointer, current task, handoff and .codex agent guides, use same branch/worktree, correct release docs and PR body, verify pinned `[api]` pipx behavior in isolated temp env without production/secret access, run required tests/compile, push/verify exact-SHA CI and request independent re-review. **No merge, deploy, service restart or production modification.**
