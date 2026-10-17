# Current task — ref-cli

- **State:** Issue #18 implementation is in [draft PR #19](https://github.com/draeician/ref/pull/19) and **INDEPENDENT QA REQUIRES CHANGES**; do NOT merge or deploy. Exact reviewed implementation SHA `2b0fba7e64888ce14a700281379a0de0778baf54`, GitHub PR CI https://github.com/draeician/ref/actions/runs/38998361423 SUCCESS (`355 passed, 1 warning` independently verified from job log).
- **Canonical active QA task:** [7e4c9b12 — fix concurrency, discovery latency and queue durability](../tasks/7e4c9b12-issue-18-qa-corrections.md).
- **Original implementation task:** [d0c54a91 — background YouTube show-note processing](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development branch:** `fix/issue-18-youtube-show-notes-timeout`, PR #19 open/draft, base `main` `799b10f28dd3776a8d9904509d166368e289bb7c` unchanged on review.
- **Handoff:** [agent-handoff.md](agent-handoff.md).
- **Prior release:** issue #15 cooldown merged in PR #16; minion CLI and API confirmed `1.6.12b1.dev79+g799b10f28` and cooldown logged one 3600-second block. That feature works but does not resolve this distinct HTTP latency issue or operator stop-in-flight disconnect.

## Architect QA, exact application SHA 2b0fba7e

**Accepted progress:** YouTube child playlist no longer directly expands full playlist in the parent request, local file-backed jobs persist by atomic `os.replace`, and 355 tests pass. Scope restricted to issue #18 source/tests/docs.

**Blocking defects (required correction task 7e4c9b12):**

1. `_process_queued_job -> process_one` holds global `_write_lock` during lengthy child provider work. A **second** concurrent parent HTTP ingest waits on that lock and can time out. Existing regression only tests the **first** parent before its worker gets the lock.
2. `_enqueue_youtube_show_notes -> read_video_card` still performs potentially slow network metadata discovery synchronously after the parent capture but before the HTTP response.
3. `ShowNotesQueue._load` silently converts corrupted/unreadable existing queue to empty, then an enqueue may overwrite accepted pending jobs. Must fail closed/surface error, never silently discard work.
4. Terminal jobs are never compacted, and completed children are re-enqueued on repeated already-recorded parent submissions; queue can grow without bound and reprocess links. `enqueue` rewrites/fsyncs full JSON for each of up to 50 links.
5. Lifecycle audit: `stop` timeout can leave daemon worker alive while singleton is nulled; a new lifespan can spawn a duplicate worker sharing the queue.

**Next actor:** OpenCode implementer on the same isolated branch/PR, deterministic fail-before fix-after regressions for slow-child concurrent second parent, stalled metadata discovery, corrupt queue preservation, duplicate completed rediscovery/retention, and worker stop/restart. Preserve issue #15 cooldown and direct playlist behavior; full pytest, compileall and diff check; update canonical handoff and draft PR; verify exact final SHA PR CI; return `[REVIEW-REQUEST]`. No production mutation, merge, direct push to main, or secret access.

## Exactly one next step

OpenCode: execute task `7e4c9b12`, then request independent architect QA on the exact new PR #19 head.
