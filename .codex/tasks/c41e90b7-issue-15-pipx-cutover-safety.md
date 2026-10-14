# [docs] Issue #15 cutover preflight correction: safe pipx upgrade/rollback

- Task ID: c41e90b7
- State: QUEUED — blocking release/cutover preflight acceptance (NOT blocking previously approved cooldown code)
- Draft PR: https://github.com/draeician/ref/pull/16
- Development branch: `fix/issue-15-ref-api-disconnect`
- Independently reviewed preflight SHA: `5747ff15aaaad1df998c3dae750d5f82bb24d090`
- Protected default branch: `main` at `276ea2afdfd8ea401f1849ba50b847225487f9ee`
- Previous preflight task: `.codex/tasks/a92d761e-issue-15-cutover-preflight.md`
- Canonical status/handoff: `.codex/notes/current-task.md`, `.codex/notes/agent-handoff.md`.

## Independent verification / accepted findings

- Workflow `.github/workflows/tests.yml` now runs on pushes to `main` and the feature branch, and pull requests. No code changes from prior QA-accepted implementation SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`.
- Exact SHA `5747ff15aaaad1df998c3dae750d5f82bb24d090` CI: push https://github.com/draeician/ref/actions/runs/38635883999 and PR https://github.com/draeician/ref/actions/runs/38635892439 both completed SUCCESS, with 336 passing tests verified from both actual job logs.
- PR remained open, draft and unmerged; `main` unchanged; 4 modified files since prior planning SHA (CI workflow and canonical documentation only).
- The preflight's service state/provenance/backup evidence came from OpenCode's report after read-only minion inspection. Architect verified the repository documentation and source-level packaging implications, but did not independently connect to minion.

## Blocking finding: rollback would destroy API functionality

Both PR #16 body and `.codex/notes/agent-handoff.md` recommend `pipx install --force 'ref-cli==1.6.11'` as a rollback alternative. **Do not use that fallback.** Repository `README.md` explicitly describes `1.6.11` as the last PyPI release *before* the FastAPI/ref-api functionality, so rolling back to that version may remove `ref-api` and fail the service. Our actual pre-cutover installation is a pipx, non-editable local-source build from `file:///opt/md2/git/personal/ref` at `main` commit `276ea2afdfd8ea401f1849ba50b847225487f9ee`. The rollback target must restore **that precise API-capable baseline**, not an unrelated old PyPI release.

The proposed `pipx install --force 'git+https://github.com/draeician/ref.git@<sha>'` is also insufficiently validated for API runtime dependencies: `fastapi` and `uvicorn` are `[api]` optional dependencies, while the current installed pipx environment may have had `ref-cli[api]` injected. An ordinary `pipx install --force` can replace the environment and should **not be assumed** to preserve injected extras or availability of `ref-api` until demonstrated.

Lastly, blindly restoring an old `references.md` backup after an otherwise code-only rollback risks **silently losing entries written after the snapshot**. Application/package rollback should normally retain current archives. Restoring archive data requires independently justified recovery from demonstrated corruption and must account for writes after the snapshot, not routine package rollback.

## Required narrowly-scoped correction

1. **Read-only verify existing install** from reported minion metadata (can re-run observational commands without printing secrets): installed package source, version, `pipx list --include-injected`, `ref-api` entry point, and whether FastAPI/uvicorn dependencies are injected. Do not read `~/.ssh`, modify credentials, start/stop production units, or install to production.
2. **Isolated packaging smoke test:** In a TEMPORARY directory/environment (dedicated `PIPX_HOME` and `PIPX_BIN_DIR`, outside archive/service/repo), prove a SHA-pinned install of the repo with `[api]` extras yields executable `ref` and `ref-api` and that `ref-api` imports FastAPI/uvicorn. Prove a similarly pinned reinstall of the old **API-capable** SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee` keeps the API executable. Use the actual verified pipx/VCS extras syntax. Do **not** issue test POSTs to production or start a production service. If offline/tool unavailable, document unverified mechanics and demand a separate verified operator dry run before deployment.
3. **Fix documentation and PR #16 body**: replace the destructive `ref-cli==1.6.11` rollback option with the prior known API-capable SHA pinned reinstall; specify how `[api]` dependencies are installed/retained. Do not claim `pipx upgrade` fetches unreleased GitHub code. Prefer one consistent proven SHA-pinned install/rollback strategy. Remove routine archive restore from package rollback: preserve archive data by default; backups are disaster recovery only, with an explicit warning about losing post-snapshot writes. Record the backup creation/verification command and rollback/check steps, staged version and health verification.
4. **Do not change cooldown code/test behavior**, main, systemd units or production package; task is release procedure correctness only. Keep `POST /urls` still potentially disconnecting during systemd shutdown explicit. No authorization for merge, deploy, restart, or live ingest.
5. **Task state/handoff**: change `.codex/notes/current-task.md` and `.codex/notes/agent-handoff.md` to summarize observed preflight, packaging smoke commands and results, changed areas, risks, true final remote SHA/CI, and exactly **one** next step.
6. **Verify** full `python3 -m pytest -q`, `python3 -m compileall -q src get_transcript.py`, `git diff --check`; update SAME draft PR #16. Push only development branch, verify GitHub Actions push and PR both completed SUCCESS on exact final remote head SHA, and report `[REVIEW-REQUEST]`.

## Acceptance

- No application code changes and no production mutations or secret reads.
- README/PR body/handoff no longer suggests pre-API 1.6.11 as routine rollback or unconditional archive restore.
- Actual pipx installation/rollback syntax and `[api]` availability verified in **isolated temp** environment, or explicit truthful blocker documented if unable to verify.
- Exact new branch/PR SHA and both green CI workflow links, no merge/deploy.
- No parallel task/handoff system.

## Exactly one next step

OpenCode: execute this narrow packaging/cutover-procedure correction and request an independent re-review before any merge-authorization decision.
