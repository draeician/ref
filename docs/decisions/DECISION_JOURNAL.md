# Decision Journal — ref

Tracked, append-only record of consequential implementation decisions. New
entries go at the bottom. Supersede an entry explicitly rather than rewriting
history.

## 2026-11-27 — Authoritative primary capture and async Reddit discovery

**Context.** refwatch's release blockers showed that ref-api inferred ingest
status from ref-cli stdout and returned the requested URL rather than the URL
stored in `references.md`. A child URL's output could change the parent status.
Retries had no idempotency contract, exact lookup used substring search, and
Reddit discovery ran synchronously and recursively on the `POST /urls` path.

**Decision 1 — capture at the archive boundary, not stdout.**
Add `ref_cli.capture`: a thread-local, first-writer-wins recorder called at
every archive write / exact existing-row check. `process_url` enters a nested
capture frame so recursive child processing is ignored for the primary result.
`ref-api` verifies the recorded stored URL with an exact parsed-row lookup before
returning `added` or `exists`.

Alternatives rejected: parsing combined stdout (already proven unsafe), changing
`process_url` to return a large result object through every recursive caller
(high blast radius; local CLI behavior would change).

**Decision 2 — `secondary` state is additive files, not a queue migration.**
Identity and idempotency state live in `<references>/ref_api_state/*.json` using
the same atomic JSON + process-local lock conventions as `show_notes_queue`.
`jobs.json` is not rewritten by this change. Existing queue snapshots load
unchanged.

**Decision 3 — reuse `discover` jobs for Reddit with an optional `source`.**
A new job kind would make an older ref-api treat the queue as corrupt on
rollback. The additive `source` field defaults to `youtube` for existing
snapshots. Older code ignores it and degrades a pending Reddit discovery job to a
no-op YouTube discovery; rollback therefore loses pending Reddit discovery but
does not corrupt or discard accepted jobs. A dedicated kind would be cleaner but
violates rollback/queue compatibility.

**Decision 4 — idempotency is at-least-once with idempotent effects.**
`Idempotency-Key` state is written before work and after each input. A retry
re-checks exact archive rows and relies on queue URL dedup, so it cannot append a
second reference or create a second discovery job. Reusing a key with a different
payload is rejected (409). We deliberately do not claim exactly-once execution:
the first response can be lost, and `force` requests only suppress duplicate
execution for the *same* key/payload.

**Decision 5 — exact lookup returns five outcomes, never a guess.**
`exists` is an exact parsed row. `canonical` requires a persisted identity from
an earlier confirmed capture. `absent` means no exact/recorded match. `unknown`
covers invalid identity or a recorded canonical row that is missing. `error`
covers archive/ledger failures. Substring matches and on-the-fly normalization
are not evidence. A fail-safe client should keep its message on `unknown`/`error`.

**Decision 6 — Reddit sync discovery stays for local CLI mode, not the API.**
`process_url(..., discover_reddit_links=False)` is used by ref-api, which then
durably enqueues discovery. Local `ref` processing retains the historical
synchronous path. Worker-spawned children disable both YouTube and Reddit
discovery, preventing recursive expansion.

**Decision 7 — lynx is invoked as argv, not a shell string.**
`subprocess.run` now gets a list and no `shell=True`, so its timeout kills the
actual lynx process instead of leaving a shell/child behind. The URL remains a
single argv element, so shell metacharacters are inert.

**Consequences / limits.**

- Archive writes remain under the existing process-local `archive_lock`; no
  second writer was introduced.
- Idempotency coordination is in-process. Cross-process/multi-worker exactly-once
  is not claimed.
- Completed idempotency entries are retained 30 days and capped at 1000; pruning
  an old key makes it new again.
- Identity state is bounded at 5000 entries.
- Rollback of ref-api to this change's predecessor loses pending Reddit
  discovery jobs (they remain `done` no-ops) but preserves the queue table.
- Production queue migration is neither needed nor authorized.

## 2026-11-27 — Corrective review: crash recovery, transactional writes, rollback safety

**Context.** Review of PR #43 found correctness gaps in the first pass: a forced
retry could repeat an already-committed archive write; queue/state mutations were
published in memory before persistence succeeded (phantom accepted state); and
the documented downgrade behavior silently lost pending Reddit discovery. Primary
successes could be downgraded by later playlist-child exceptions, and diagnostics
were not proven credential-safe.

**Decision 8 — per-input attempt fingerprints + explicit `ambiguous` state.**
Before a forced input writes, the service persists a SHA-256 fingerprint of
`references.md`. On a retry with no persisted result, an unchanged fingerprint
proves re-execution is safe. A changed fingerprint (the write may have committed
before the crash) is not reconcilable without risking a duplicate, so the key is
persisted as `ambiguous` and subsequent requests fail closed with `409`. A
non-forced retry remains safe because exact-row checks and queue dedup make
re-processing idempotent. `force` is part of the request hash, so a key cannot be
silently reused with different authorization. Results (including `null` holes)
stay positionally bound to the original ordered inputs.

Alternatives rejected: re-running forced work after a changed fingerprint
(duplicate rows); inferring success from the presence of any row (cannot prove it
was written by this attempt); treating a URI-identity match as proof of this
attempt's write (redirects/canonicalization make it ambiguous).

**Decision 9 — copy-on-write persistence for queue and state stores.**
Every mutation builds a new job/identity/request table, writes it to a unique
temp file, flushes and `fsync`s the file, atomically `os.replace`s the target,
best-effort `fsync`s the directory, and only then publishes the new table in
memory. A failure at dump, file fsync, or replace leaves the old in-memory table
and old file intact, so a request never observes `queued`/`already_queued`, a
durable identity, or a successful replay that was not actually persisted. A
corrupt file is refused before any write, preserving its bytes.

Note on guarantees: atomic replace prevents torn reads, and file fsync precedes
the rename. Directory fsync is best-effort and logged if unsupported; the rename
commit is already visible. This is single-writer-per-process durability, not
cross-process mutual exclusion or power-loss proof on filesystems that ignore
fsync.

**Decision 10 — block downgrade while incompatible discovery is outstanding.**
Supersedes the rollback consequence in Decision 3. Preserving the queue file is
not enough: an older ref-api consumes a pending Reddit `discover` job as a no-op
YouTube job and marks it `done`, losing the discovery. The current build exposes
`GET /queue/rollback-safety` and `ref-api --rollback-check` (exit 0 safe, 2
blocked). Pending/running Reddit discovery or a corrupt queue blocks downgrade;
`done`/`failed` jobs do not. The check is read-only — no queue snapshot is ever
deleted, rewritten, or migrated. Operators must drain the queue on the current
build before downgrading.

**Decision 11 — primary success is isolated from auxiliary failures.**
`process_one` recovers the recorded primary capture even when `process_url`
raises after the archive commit (for example a playlist-child or formatting
failure). It re-verifies the exact row, records identity best-effort, reports the
auxiliary failure in `output`, and returns the authoritative `primary` with its
`added`/`exists` status. Discovery enqueue and identity bookkeeping were already
auxiliary; this closes the remaining playlist-child path.

**Decision 12 — deletion safety is an explicit proof, not an inference.**
`GET /urls/exists` includes `deletion_safe`, true only for a proven exact row or a
persisted canonical identity whose exact row exists. `absent`, `unknown`, and
`error` are explicitly documented as *not* proof that an unresolved canonical
reference was never captured. Deletion workflows must fail closed.

**Decision 13 — sanitize at every diagnostic boundary.**
`redact_credentials` strips URL userinfo and token-like query/fragment values
without flattening; `sanitize_error_detail` then bounds and flattens for API
responses and one-line logs. The file error logger and lynx argv diagnostics use
it. Regression tests cover userinfo, API keys, access tokens, signatures,
fragment tokens, error-log files, and a failing captured URL.

**Consequences / limits (correction).**

- The previous "rollback loses pending Reddit discovery" consequence is
  superseded: downgrade is blocked instead.
- `ambiguous` keys are retained indefinitely; a new key is required to perform a
  new forced capture. This is intentional fail-closed behavior.
- Fingerprint comparison detects any archive change, including unrelated writes;
  an ambiguous result can be conservative but never duplicates a forced write.
- Transactional tests inject failures at `json.dump`, file `os.fsync`, and
  `os.replace`, not only at high-level methods.
