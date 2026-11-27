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

### Corrective review pass

- **Forced crash recovery.** `IdempotencyStore` keeps positionally aligned
  `attempts` (`archive fingerprint`, `started_at`) alongside `results`. Before a
  forced write, `references.md` is fingerprinted and persisted. An interrupted
  forced retry with an unchanged fingerprint resumes; a changed fingerprint
  marks the key `ambiguous`, and later requests fail closed with `409`. Non-forced
  retries stay safe via exact-row checks and queue dedup. `force` is part of the
  request hash, and results (including `null` holes) remain bound to input order.
- **Transactional persistence.** Added `src/ref_api/atomic_json.py` (unique temp
  file, write + file `fsync`, `os.replace`, best-effort directory `fsync`).
  `ShowNotesQueue`, `UrlIdentityStore`, and `IdempotencyStore` now mutate a copy,
  persist it, and only then publish it in memory. Dump/fsync/replace failures
  leave no phantom `queued`/durable identity/replay state and never overwrite a
  corrupt file.
- **Rollback safety.** `ShowNotesQueue.rollback_blockers()`,
  `GET /queue/rollback-safety`, and `ref-api --rollback-check` block downgrade
  while any Reddit discovery job is **pending, running or failed** (or the queue
  is corrupt). Pending/running jobs would be consumed as no-op YouTube jobs;
  failed jobs would lose their `source` metadata because the base reader
  (`_normalize_job` at `57abe0f`) drops unknown fields on its next snapshot
  write. `done` jobs do not block. The check is read-only and the documented
  authoritative procedure is offline after the service stops; no snapshot is
  deleted, rewritten, or migrated.
- **Primary isolation.** `process_one` recovers the recorded primary capture even
  when `process_url` raises after the archive commit (playlist child/formatting),
  re-verifies the exact row, and reports the auxiliary failure without changing
  `primary`. Discovery/identity failures were already auxiliary.
- **Deletion safety.** `GET /urls/exists` now returns `deletion_safe`, true only
  for a proven exact/canonical-present row; `absent`/`unknown`/`error` are
  documented as not proving absence.
- **Diagnostics.** `redact_credentials` + `sanitize_error_detail` redact URL
  userinfo and token-bearing query/fragment values at the API, file-log, and lynx
  diagnostic boundaries; regression tests cover credential-bearing inputs.

### Second corrective review pass

- **Old-reader metadata loss.** Confirmed at base `57abe0f`:
  `_normalize_job()` returns a fixed dict with no `source` field, and `_snapshot`
  rewrites the whole table from those records. A downgrade therefore strips
  `source` from every job on the older build's next mutation, including a
  terminal failed Reddit discovery job. The previous "failed jobs do not block"
  rule was wrong.
- **Guard corrected.** `rollback_blockers()` now includes `failed` Reddit
  discovery jobs alongside `pending`/`running`. `failed_preserved` counts the
  failed jobs that block. `done` jobs still do not block.
- **Compatibility regression.** `test_legacy_queue_snapshot_strips_source_from_failed_jobs`
  reproduces the base reader/writer: load → normalize away `source` → old-style
  `recover()` snapshot → assert the failed Reddit job survives only as a
  YouTube-default job. It also asserts the current guard blocks first.
- **Race-free procedure.** README/task/HANDOFF now require: stop incoming
  submissions, stop `ref-api`, run `ref-api --rollback-check` against the final
  persisted queue, and back up `jobs.json` before downgrading. The live endpoint
  is advisory, not the deciding check.

## Verification evidence

Environment: isolated venv `/tmp/opencode/ref-venv` (Python 3.14.4,
`uv pip install -e '.[api,test]'`).

- PR CI (`pytest`) passed on the original head; correction-head CI is recorded on
  [#43](https://github.com/draeician/ref/pull/43/checks) after push.
- First correction commit
  `08b95b80e4cfc46a8ea997206cb78ceca679f2da`; exact-head CI run
  `45952664641` passed (`pytest`: `689 passed`).
- Second rollback-correction commit
  `1e1fb4b2c2fd0f2eca7320c25f01d7d7c2db9e22`; exact-head CI run
  `46028605496` passed (`pytest`: `690 passed, 1 warning in 20.23s`). A
  docs-only follow-up records this evidence.
- `python -m pytest -q` → **690 passed, 1 warning** (Starlette TestClient
  deprecation only). New coverage: transactional write/fsync/replace failures
  (queue enqueue/batch/claim/terminal transitions, identity and idempotency
  begin/update, corrupt-file byte preservation), six interruption points ×
  `force=false`/`true`, downgrade safety (pending/running/**failed**/corrupt,
  read-only route/CLI, and a base-`57abe0f` reader/snapshot compatibility
  regression proving failed Reddit jobs lose `source`), primary isolation from
  discovery and playlist-child failures, deletion-safety semantics, and
  credential redaction.
- `python -m compileall -q src` → OK.
- `uv build` (equivalent package build; the local `build/` directory shadows the
  `build` module when invoked as `python -m build`) → sdist and wheel built
  successfully.
- `git diff --check` → clean.
- Isolated pipx install from the working tree with `[api]` into a fresh
  `HOME`/`PIPX_HOME`. Verified over real HTTP in the previous pass:
  `/health` and `/capabilities` reported `api_contract_version: "2"` plus the new
  feature flags; PDF ingest returned structured `added` with an exact confirmed
  canonical URL; exact lookup returned `exists`/`deletion_safe: true`; an absent
  URL returned `absent`/`deletion_safe: false`; idempotent replay returned
  `Idempotent-Replayed: true`; a changed payload returned `409`;
  `/requests/{key}` returned `completed` with positional results.
- **Offline rollback check (final pass):** with a failed Reddit discovery job in
  the persisted queue, `ref-api --rollback-check` reported `blocked`
  (`failed_preserved: 1`, status `failed`, reason cites `source`) and exited `2`;
  the `jobs.json` SHA-256 was unchanged. After resolving that job to `done`, the
  same offline check reported `safe` and exited `0`. A `done` Reddit job and an
  unrelated YouTube discovery did not block. This exercises the exact procedure
  documented for operators (service stopped, final queue file).
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
  are unchanged. `GET /capabilities` advertises contract version `2` plus
  `deletion_safe_lookup`, `idempotency_ambiguous_state`, and
  `rollback_safety_check`.
- `jobs.json` is not migrated. Existing snapshots without `source` load as
  YouTube. **Downgrade is blocked while any Reddit discovery job is pending,
  running or failed** (or the queue is corrupt):
  - pending/running jobs would be consumed as no-op YouTube jobs;
  - failed jobs would lose their `source` field on the older build's next
    snapshot write (base `_normalize_job` reconstructs without it).

  Use the offline procedure: stop submissions, stop `ref-api`, then run
  `ref-api --rollback-check` (exit 0 safe / 2 blocked) against the final queue
  and back up `jobs.json`. `GET /queue/rollback-safety` is read-only advisory.
  `done` jobs do not block. No snapshot is deleted or rewritten.
- Identity/idempotency files are additive under `ref_api_state/`; deleting them
  only loses reconciliation history, not archive rows. Ambiguous idempotency
  entries are retained until resolved with a new key.
- Planned next SemVer: **1.7.0** (documented only; no tag or release in scope).

## Known limitations

- Idempotency key serialization is process-local (same model as the archive and
  queue locks). Multi-process/write-replica exactly-once is not claimed.
- Atomic writes give torn-read safety and file-level `fsync` durability; directory
  `fsync` is best-effort. This is not a claim of power-loss proof on filesystems
  that ignore `fsync`, nor cross-process mutual exclusion.
- A changed archive fingerprint marks an interrupted forced request `ambiguous`
  even when the change came from unrelated work; the outcome is conservative but
  never duplicates a forced write. Resolve by using a new key.
- `archive_lock` remains process-local; no second archive writer was added.
- `unknown`/`error`/`absent` lookup outcomes must be treated as "not proven
  present" by fail-safe clients (`deletion_safe: false`).
