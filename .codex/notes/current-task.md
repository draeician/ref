# Current task — ref-cli

- **State:** Issue #18 corrections implemented on draft [PR #19](https://github.com/draeician/ref/pull/19); **awaiting independent architect QA**; do NOT merge or deploy. Correction commit `559767654a117dcc20564a3f4f39ab321476d20e` on branch `fix/issue-18-youtube-show-notes-timeout`.
- **Canonical active QA task:** [7e4c9b12 — fix concurrency, discovery latency and queue durability](../tasks/7e4c9b12-issue-18-qa-corrections.md) (IMPLEMENTED).
- **Original implementation task:** [d0c54a91 — background YouTube show-note processing](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md) (IN-REVIEW, not QA-approved).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development branch:** `fix/issue-18-youtube-show-notes-timeout`, PR #19 open/draft, base `main` `799b10f28dd3776a8d9904509d166368e289bb7c` unchanged.
- **Handoff:** [agent-handoff.md](agent-handoff.md).
- **Prior release:** issue #15 cooldown merged in PR #16; distinct from this HTTP-latency issue.

## Architect QA corrections (task 7e4c9b12) — implemented 2026-10-17

The five blocking defects from the first QA review of SHA `2b0fba7e` were all
corrected in commit `559767654a117dcc20564a3f4f39ab321476d20e`:

1. **Concurrency** — worker no longer holds `_write_lock` across slow
   provider/network work; a CLI-level `_archive_lock` serializes only short
   archive read/write critical sections; stdout capture is thread-local.
2. **Discovery off the parent path** — `process_one` enqueues a `discover` job;
   the worker fetches the card and batch-enqueues `ingest` jobs.
3. **Fail-closed queue** — corrupt `jobs.json` raises `QueueCorruptError`, is
   never overwritten, and surfaces via `/queue` (`corrupt` field).
4. **Bounded history/dedup** — done work is not re-enqueued, terminal history is
   compacted, children are batch-enqueued.
5. **Worker lifecycle fence** — `stop()` leaves the singleton set during a slow
   drain so `start()` cannot spawn a duplicate worker.

Local evidence: `python -m pytest -q` → **362 passed** (355 prior + 7 new);
`compileall -q src tests` OK; `git diff --check` clean.

**Next actor:** independent architect QA on the exact new PR #19 head (after
push + docs commit). OpenCode must push, update the draft PR body, and verify
GitHub PR CI on the exact final remote SHA, then return `[REVIEW-REQUEST]`. No
production mutation, merge, direct push to `main`, or secret access.

## Exactly one next step

OpenCode: push `fix/issue-18-youtube-show-notes-timeout`, update draft PR #19,
verify exact-final-SHA CI, then request independent architect QA on PR #19.
