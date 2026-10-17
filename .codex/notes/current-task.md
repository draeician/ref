# Current task — ref-cli

- **State:** **Issue #18 PR #19 — second QA corrections IMPLEMENTED, awaiting independent architect re-review.** The three blockers from the second review (archive integrity, complete queue validation, worker resume) are corrected with deterministic fail-before/pass-after regressions. Do NOT merge/deploy.
- **Canonical active corrective task:** [4f29b6c1 — archive serialization, complete queue validation and worker recovery](../tasks/4f29b6c1-issue-18-qa-archive-persistence-lifecycle.md) (IMPLEMENTED).
- **Previous correction task:** [7e4c9b12 — slow worker/discovery/corruption/history/lifecycle](../tasks/7e4c9b12-issue-18-qa-corrections.md) (five changes implemented).
- **Original implementation task:** [d0c54a91 — background YouTube show notes](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18.
- **Development branch:** `fix/issue-18-youtube-show-notes-timeout`, existing [draft PR #19](https://github.com/draeician/ref/pull/19); protected `main` unchanged at `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Handoff:** [agent-handoff.md](agent-handoff.md).

## Second-QA corrections (task 4f29b6c1) — implemented

- **P0 archive integrity.** New `src/ref_cli/archive_lock.py` (process-local `threading.RLock`), aliased as `cli._archive_lock`; `references_format.apply_row_updates` + `migrate_references_file` and `enrichment.enrich_youtube_reference` (gather+apply) commit under it; `update_transcript` moved its network fetch outside the lock. Regression `tests/test_archive_integrity.py` verified fail-before/pass-after.
- **P0 queue validation.** `show_notes_queue._load` reads bytes, decodes/parses/validates under one fail-closed boundary; `_loaded` set only after success or explicit corruption; full per-field validation (id-consistency, kind, status, attempts, timestamps, …). Original bytes preserved on every malformed path.
- **P1 worker lifecycle.** `_restart_pending` + `_worker_exited` successor handoff; timed-out stop followed by restart resumes draining via a successor (never two draining workers).
- **Gates:** `pytest -q` → **372 passed, 1 warning** (was 362); `compileall` clean; `git diff --check` clean.

## Authorization

OpenCode may correct code/tests/docs on the existing feature branch and draft PR #19, preserve WIP. No direct main push, merge, production pipx/restart, changes to `~/references`, live ingest or secret inspection.

## Exactly one next step

Push the existing branch, verify exact-final-SHA PR CI green, and return `[REVIEW-REQUEST]` for independent architect QA.
