# Current task — ref-cli

- **State:** **DONE — approved for repository merge**; task record moved to
  `.codex/tasks/done/`. Repository merge is the only remaining action.
- **Task record:** [3b614093 — authoritative capture + async Reddit discovery](../tasks/done/3b614093-authoritative-capture-reddit-discovery.md).
- **Approval:** ChatGPT approved repository merge on 2026-11-27 at HEAD
  `69af2d6ab193ceec0092d8e3a37f07360811edbe`, authorized by Drae.
- **Branch:** `fix/api-primary-capture-and-reddit-discovery` (base
  `origin/main` `57abe0f276caa96990d35f46e21d514a73ed7748`).
- **PR:** [#43](https://github.com/draeician/ref/pull/43) — approved, marked
  ready and merged with a normal merge commit; merged branch deleted.
- **Scope:** backend/code/tests/docs in `draeician/ref` only. refwatch, PR #29,
  production services, the production archive/queue, NFS/local-transcribe,
  and release tagging remain untouched.
- **Contract:** `POST /urls` adds `primary`/`discovery` (existing fields
  preserved); `GET /urls/exists` is read-only and includes `deletion_safe`;
  `GET /capabilities` advertises `api_contract_version: "2"`;
  `GET /requests/{key}` is read-only positional reconciliation.
- **Verification:** `python -m pytest -q` → 690 passed, 1 warning;
  `python -m compileall -q src` → OK; `uv build` → sdist + wheel; `git diff
  --check` → clean; approved-head CI run `46028919395` → 690 passed; isolated
  pipx `[api]` install passed health, capabilities, capture, exact lookup,
  idempotent replay and 409 conflict checks; offline `ref-api --rollback-check`
  blocked on a failed Reddit job (exit 2, queue bytes unchanged) and passed
  after resolution (exit 0).
- **Next SemVer:** 1.7.0 (documented only; not tagged or released).
- **Known limits:** process-local idempotency/archive coordination; no
  multi-process exactly-once claim. Downgrade is blocked while Reddit discovery
  jobs are pending, running or failed because the older reader strips the
  additive `source` field; `done` jobs do not block.

## Exactly one next step

None beyond repository merge/cleanup. Do not tag, publish, deploy, restart
services, or touch production state.
