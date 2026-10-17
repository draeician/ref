# Current task — ref-cli

- **State:** **Issue #18 PR #19 REQUIRES FURTHER CORRECTIONS** after second independent architect source review at application SHA `559767654a117dcc20564a3f4f39ab321476d20e`, reviewed final remote SHA `e83c468964db1e1cb600fb657cd446ab8bbcac99`. Tests pass but new archive integrity, fail-closed queue and lifecycle-resume defects block merge. Do NOT merge/deploy.
- **Canonical active corrective task:** [4f29b6c1 — archive serialization, complete queue validation and worker recovery](../tasks/4f29b6c1-issue-18-qa-archive-persistence-lifecycle.md) (OPEN).
- **Previous correction task:** [7e4c9b12 — slow worker/discovery/corruption/history/lifecycle](../tasks/7e4c9b12-issue-18-qa-corrections.md) (five changes implemented, remaining edge cases detected).
- **Original implementation task:** [d0c54a91 — background YouTube show notes](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development branch:** `fix/issue-18-youtube-show-notes-timeout`, existing [draft PR #19](https://github.com/draeician/ref/pull/19); protected `main` unchanged at `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Handoff:** [agent-handoff.md](agent-handoff.md).
- **Prior production:** issue #15 cooldown merged and minion confirmed on release `g799b10f28`, 60-minute cooldown seen working; this does not imply #18 fixed.

## Second independent architect re-review

- **Verified directly at exact SHA** `e83c468964db1e1cb600fb657cd446ab8bbcac99`: branch == PR head, PR open/draft, main unchanged. PR GitHub Actions https://github.com/draeician/ref/actions/runs/39000511326 **SUCCESS**; direct job log **362 passed, 1 warning in 9.78s**. OpenCode reported local compileall/diff check; architect did not run them.
- **Accepted progress:** metadata discovery off request path; slow child no longer globally holds the service lock; thread-local stdout capture; file-backed discover/ingest queue, bounded history and batch child enqueue; fail-closed for invalid JSON/basic malformed schema; worker singleton retained on timed-out stop; tests added for each.
- **BLOCKER 1 — archive data loss:** `src/ref_cli/enrichment.py:enrich_youtube_reference` still calls whole-archive read/rewrite `references_format.apply_row_updates` **outside** new `_archive_lock`. Concurrent reference append/rewrite may be silently lost; the regression for slow child mocks `ref_cli.process_url` and never exercises real enrichment. Full audit and serialization of actual commit sections required.
- **BLOCKER 2 — bypassed queue corruption detection:** `src/ref_api/show_notes_queue.py:_load` sets `_loaded=True` before validation. `_valid_job` ignores `attempts` type and can throw on unhashable `status`; `_normalize_job` `int(attempts)` can raise `ValueError`. Next enqueue sees loaded+not-corrupt and may overwrite accepted original `jobs.json`. Full validation and fail-closed guard required.
- **BLOCKER 3 — worker lost after restart:** `stop_show_notes_worker()` retains a still-running stop-signaled worker; `start_show_notes_worker()` returns while it is alive; after that worker completes and exits, restarted lifespan has no worker. Test currently verifies no overlap but not successful resume. Add resume/handoff proof.
- The detailed findings and fail-before/pass-after acceptance are in **task `4f29b6c1`**. The initial issue #18 incident was an 8-minute blocked child-link run after a 300-second client timeout, while the parent was already recorded.

## Authorization

OpenCode may correct code/tests/docs on the existing feature branch and draft PR #19, preserve WIP. No direct main push, merge, production pipx/restart, changes to `~/references`, live ingest or secret inspection. Earlier authorization to deploy issue #15 does NOT authorize #18.

## Exactly one next step

OpenCode: implement `4f29b6c1`, run focused races/full suite/compile/diff checks, push existing branch, verify exact-final-SHA PR CI and return `[REVIEW-REQUEST]` for independent architect QA.
