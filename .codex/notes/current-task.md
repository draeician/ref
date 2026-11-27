# Current task — ref-cli

- **State:** **REVIEW** — authoritative primary capture, exact archive lookup,
  durable `Idempotency-Key`, and asynchronous Reddit discovery.
- **Task record:** [3b614093 — authoritative capture + async Reddit discovery](../tasks/review/3b614093-authoritative-capture-reddit-discovery.md).
- **Branch:** `fix/api-primary-capture-and-reddit-discovery` (base
  `origin/main` `57abe0f276caa96990d35f46e21d514a73ed7748`).
- **PR:** opened after the verification gate; see the task record for the
  final link. Draft/open only — do **not** merge or deploy without Drae's review
  and explicit authorization.
- **Scope:** backend/code/tests/docs in `draeician/ref` only. refwatch, PR #29,
  production services, the production archive/queue, NFS/local-transcribe,
  and release tagging are untouched.
- **Contract:** `POST /urls` adds `primary`/`discovery` (existing fields
  preserved); `GET /urls/exists` is read-only; `GET /capabilities` advertises
  `api_contract_version: "2"`; `GET /requests/{key}` is read-only reconciliation.
- **Verification:** `python -m pytest -q` → 623 passed, 1 warning;
  `python -m compileall -q src` → OK; `uv build` → sdist + wheel; `git diff
  --check` → clean; isolated pipx `[api]` install with fresh HOME/archive and
  loopback port passed health, capabilities, capture, exact lookup, idempotent
  replay and 409 conflict checks.
- **Next SemVer:** 1.7.0 (documented only; not tagged or released).
- **Known limits:** process-local idempotency/archive coordination; no
  multi-process exactly-once claim; rollback loses pending Reddit discovery but
  preserves queue rows and archive data.

## Exactly one next step

ChatGPT/Drae review PR for task `3b614093`. Do not merge, deploy, restart
services, or touch production state until that review and explicit
authorization are complete.
