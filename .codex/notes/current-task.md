# Current task — ref-cli

- **State:** Issue #15 transcript cooldown implementation QA PASSED at code SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`. Main-push CI trigger landed and read-only preflight reviewed at `5747ff15aaaad1df998c3dae750d5f82bb24d090`. The blocking rollback/packaging defect is **CORRECTED (task c41e90b7)**: rollback now targets the prior API-capable SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee` (never pre-API `1.6.11`), the SHA-pinned `ref-cli[api]` install/rollback was verified in an isolated temp pipx env, and archive data is preserved by default. **Awaiting independent re-review**; not merged/deployed (user conditionally authorized the eventual merge+deploy when gates pass).
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

## c41e90b7 correction result (OpenCode, 2026-10-15)

- Fixed release instructions: rollback now uses the prior **API-capable** revision — `pipx install --force 'ref-cli[api] @ git+https://github.com/draeician/ref.git@276ea2afdfd8ea401f1849ba50b847225487f9ee'` — and explicitly forbids pre-API `ref-cli==1.6.11`. Code phase-in uses the same `[api]`-inclusive SHA-pinned spec (one step; no separate `pipx inject`).
- Verified in an isolated throwaway `PIPX_HOME`/`PIPX_BIN_DIR` under `/tmp` (never production): final branch tip `3626d65` → `ref 1.6.12b1.dev77+g3626d65bc`, `ref-api --help` exit 0, `fastapi`/`uvicorn`/`ref_api.app` import OK; `--force` reinstall at `276ea2afd` → `ref 1.6.12b1.dev40+g276ea2afd` (matches production baseline), `ref-api` functional. Temp dir removed; GitHub reachable from minion.
- Archive safety: package rollback replaces only the pipx venv; `~/references` (644M) is untouched. Old `references.md` backups are disaster recovery only, with an explicit post-snapshot data-loss warning.
- Read-only production provenance reconfirmed: base `dev40+g276ea2afd` local-dir install + injected `dev15+g5642e2e44`; venv `fastapi 0.143.0` / `uvicorn 0.54.0`.
- No application code, systemd unit, `main`, or production mutation.

## User authorization — 2026-10-14

The user explicitly authorized **merging PR #16 to `main` and deploying to production when ready**. This does not waive the currently blocking `c41e90b7` packaging/rollback smoke-test and review, required exact-final-SHA PR CI, exact-merged-main-SHA post-merge CI, verified API-capable rollback, or production idle-window checks. Architect will review corrective delivery and merge using GitHub's PR merge action (not direct push); OpenCode will operate minion only after the verified merge and release instructions are recorded. Do not claim the feature is deployed until post-install `/health` and `ref --status` match the new version and the queue/cooldown behavior is checked. If any gate fails, stop safely and report it. The user need not repeat general merge/deploy authorization.

## Next actor

OpenCode's c41e90b7 correction is complete and pushed (docs + PR body only; isolated `[api]` pipx smoke evidence recorded). The architect independently re-reviews the exact final SHA and both green workflows, then performs the authorized PR merge. After post-merge `main`-SHA CI is green, OpenCode performs the idle-window production cutover per the verified procedure (SHA-pinned `[api]` pipx install, archive preserved, health/status checks) and reports installed version, `/health`, `ref --status` and cooldown/queue evidence. **No OpenCode merge, no deploy/restart before the architect's merge and main-CI success.**
