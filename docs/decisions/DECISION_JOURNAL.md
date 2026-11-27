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
