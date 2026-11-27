# [fix] Authoritative primary capture, exact lookup, idempotency, async Reddit discovery

- **Task ID:** 3b614093
- **Owner:** OpenCode
- **State:** REVIEW
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/review/`.
- **Branch:** `fix/api-primary-capture-and-reddit-discovery`
- **PR:** [#43](https://github.com/draeician/ref/pull/43) (draft, open, **not merged**)
- **Base:** `origin/main` = `57abe0f276caa96990d35f46e21d514a73ed7748`
- **Repositories:** `draeician/ref` only. `draeician/refwatch` is read-only context.
- **Authorization:** Backend implementation, tests, docs, commit and push only. No refwatch change, merge, release, deployment, service restart, production archive/queue change, or PR #29 action.

## Claim

```
[CLAIM] 3b614093 authoritative capture + async Reddit discovery
repo: draeician/ref@fix/api-primary-capture-and-reddit-discovery
actor: OpenCode  role: Coder
task-file: .codex/tasks/wip/3b614093-authoritative-capture-reddit-discovery.md
plan:
- Produce structured primary capture from archive writes/exact verification
- Extend POST /urls with backup-compatible primary/discovery fields
- Add read-only exact GET /urls/exists with persisted identity ledger
- Add optional durable Idempotency-Key request state
- Move Reddit discovery to durable show-notes queue jobs
- Preserve existing YouTube queue jobs/snapshot compatibility
- Add deterministic regression and real-route integration tests
- Run full isolated verification gate, docs, commit, push, PR
```

## Problem

refwatch blocks production use because the backend infers ingest status from
ref-cli stdout, returns the requested URL rather than the archive-stored URL,
has no exact lookup, and cannot make retries idempotent. Reddit discovery is
also synchronous and recursive on the API request path.

## Deliverables

1. Structured primary capture (`primary.status`, stored `canonical_url`,
   `archive_confirmed`) sourced from the archive write or exact existing-row
   verification, never stdout parsing.
2. Backward-compatible `POST /urls` extension plus explicit API contract version.
3. Read-only `GET /urls/exists`.
4. Optional `Idempotency-Key` contract with durable request state and restart
   reconciliation.
5. Durable asynchronous Reddit discovery using the existing show-notes queue.
6. Regression, queue-compatibility and real-route integration tests.
7. Docs, changelog, Decision Journal and HANDOFF evidence.

## Acceptance checks

- Every supported capture path reports an authoritative stored URL and status.
- Existing PDF/playlist rows report `exists` even with empty primary stdout.
- Archive writes remain under `ref_cli.archive_lock`; no second archive writer.
- `/urls` preserves existing fields and CLI output.
- Child discovery can never overwrite primary status.
- Discovery is reported as `queued` only after durable enqueue succeeds.
- `/urls/exists` is read-only, exact-parser based, and never enqueues or writes.
- Same idempotency key + payload does not duplicate captures or jobs; different
  payload is rejected; interrupted work is recoverable without duplicate writes.
- Reddit submission destinations, body links, comment links and short links are
  discovered by the worker, bounded and deduplicated.
- Discovered playlists remain link-only; direct playlists still expand.
- Existing YouTube jobs, terminal records, retries and snapshots still load.
- No network call while holding an archive write lock.
- Full pytest/compile/build/diff gate passes in an isolated environment.

## Notes

- Repository consolidation and PR #29 are out of scope and must remain untouched.
- No production queue migration is authorized; new queue fields must be
  backward-compatible and documented for rollback.

## Implementation summary

- `src/ref_cli/capture.py` adds a thread-local, first-writer-wins capture recorder.
  `process_url` is now a thin wrapper entering a capture frame, so recursive
  child processing cannot replace the submitted URL's primary result.
- Capture is recorded at the actual archive write or exact existing-row check
  for general pages, PDFs, Rumble, Reddit, YouTube channels/community posts,
  videos, Shorts (video-id path), playlists, and suppressed link-only playlists.
- `POST /urls` now returns `primary` (`status`, stored `canonical_url`,
  `archive_confirmed`, `source`, `identity_recorded`) and a separate `discovery`
  object. `url` is the stored URL; `input` preserves request identity.
- `GET /urls/exists?url=` is read-only and uses `exact_url_rows` (exact parsed
  rows under the existing archive lock) plus the persisted identity ledger.
- `Idempotency-Key` uses durable `<references>/ref_api_state/idempotency.json`
  with per-key in-process serialization, 409 on payload reuse, replay header,
  and `GET /requests/{key}` reconciliation.
- Reddit discovery runs as a durable `discover` job on the existing worker and
  queue (`source=reddit`, additive field, default `youtube`). Children are
  independent `ingest` jobs with existing bounded retries; Reddit→Reddit links
  are filtered and worker children disable further discovery.
- `lynx` is executed as an argv list (no shell) so a timeout kills lynx itself.

## Verification evidence

Environment: isolated venv `/tmp/opencode/ref-venv` (Python 3.14.4,
`uv pip install -e '.[api,test]'`).

- PR CI (`pytest`) passed on every pushed head; see the checks on
  [#43](https://github.com/draeician/ref/pull/43/checks).
- `python -m pytest -q` → **623 passed, 1 warning** (Starlette TestClient
  deprecation only).
- `python -m compileall -q src` → OK.
- `uv build` (equivalent package build; the local `build/` directory shadows the
  `build` module when invoked as `python -m build`) → sdist and wheel built
  successfully.
- `git diff --check` → clean.
- Isolated pipx install from the working tree with `[api]` into a fresh
  `HOME`/`PIPX_HOME` and an ephemeral loopback port: `ref-api` started,
  `/health` reported `api_contract_version: "2"`, `/capabilities` matched,
  PDF ingest returned structured `added`, exact lookup returned `exists`,
  an absent URL returned `absent`, an idempotent replay returned
  `Idempotent-Replayed: true`, and a different payload returned `409`.
- Lint/type tools (`ruff`, `mypy`) are not repository dependencies and are not
  installed in the isolated environment; per repository policy no installation
  was performed. CI's configured gate is `python -m pytest -q`.

## Test boundaries

- Deterministic unit/regression tests isolate `references.md`, queue, identity
  and idempotency state under `tmp_path`. External provider/tool boundaries
  (Reddit provider, YouTube card/transcript, lynx) are patched.
- The real-route integration test uses the real FastAPI router, real archive
  parse/write, real identity/idempotency stores and a local
  `ThreadingHTTPServer` fixture. Only the title-fetch system boundary is
  replaced with a fixture HTTP GET/parse so the test works without `lynx`.
  Redirect resolution, normalization, capture verification and queue enqueue
  remain real.

## Compatibility and rollback

- Response additions are backward compatible; existing fields and CLI rendering
  are unchanged. `GET /capabilities` advertises contract version `2`.
- `jobs.json` is not migrated. Existing snapshots without `source` load as
  YouTube. Rolling ref-api back to the previous build loses pending Reddit
  discovery (new jobs degrade to no-op YouTube discovery) but preserves queue
  rows and all archive data.
- Identity/idempotency files are additive under `ref_api_state/`; deleting them
  only loses reconciliation history, not archive rows.
- Planned next SemVer: **1.7.0** (documented only; no tag or release in scope).

## Known limitations

- Idempotency key serialization is process-local (same model as the archive and
  queue locks). Multi-process/write-replica exactly-once is not claimed.
- `archive_lock` remains process-local; no second archive writer was added.
- `unknown`/`error` lookup outcomes must be treated as "not proven present" by
  fail-safe clients.
