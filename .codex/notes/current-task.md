# Current task — ref-cli

- **State:** **Issue #18 PR #19 APPLICATION CODE QA PASSED** on exact reviewed SHA `8711cf473b73c8fee34e4c635efe78dd109926ba` (app/test commit `bdd2916`). The issue #18 queue/timeout fix is reviewed and suitable for **user-authorized release planning**. **DO NOT merge or deploy until the user specifically authorizes this issue #18 rollout.**
- **PR:** https://github.com/draeician/ref/pull/19 — keep draft until user confirms authorized merge/cutover; `main` baseline `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Review comment:** https://github.com/draeician/ref/pull/19#issuecomment-6229705014 — exact-sha source review passed. The GitHub account that submitted PR cannot formally approve its own PR (422), so the architect verdict is recorded as a comment instead.
- **Exact reviewed PR CI:** https://github.com/draeician/ref/actions/runs/39002946373 — SUCCESS, independently inspected actual pytest log `389 passed, 1 warning in 11.84s`. OpenCode reports compileall and diff check clean; architect did not rerun those locally.
- **Canonical tasks:** [9b62e0c4 — non-finite timestamps/worker shutdown](../tasks/9b62e0c4-issue-18-final-queue-lifecycle-qa.md) (QA PASSED); [4f29b6c1 — archive/queue/restart](../tasks/4f29b6c1-issue-18-qa-archive-persistence-lifecycle.md) (QA PASSED); [7e4c9b12](../tasks/7e4c9b12-issue-18-qa-corrections.md) (QA PASSED); [d0c54a91](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md) (original implementation, QA PASSED).
- **Canonical handoff:** [agent-handoff.md](agent-handoff.md); issue https://github.com/draeician/ref/issues/18.
- **Prior production:** issue #15 cooldown already deployed at `g799b10f28`. No verified issue #18 deployment; current production is not running this new code.

## Architect acceptance summary (2026-10-17 UTC)

1. **Original 300s read-timeout cause:** parent API no longer synchronously discovers or processes 20–50 YouTube show-note children; a durable `discover` job fans out bounded `ingest` jobs, and automatically discovered playlists are recorded as link-only, while manually submitted playlists retain full expansion.
2. **Concurrency and data safety:** provider work is outside the new shared *process-local* archive RLock, while actual whole-file enrichment/metadata/transcript commits synchronize with archive appends. Actual concurrent enrichment rewrite regression verifies both rows survive.
3. **Queue durability:** fail-closed loading for malformed/undecodable/schema-invalid queue; new `math.isfinite` guard rejects `NaN`, `Infinity`, `-Infinity`, `1e309` persisted timestamps without overwriting jobs; bounded history/retries/dedup and `GET /queue` observability.
4. **Lifecycle:** worker exits hand off to a successor after stop→start; stop→start→stop cancels successor, no work resumes after latest shutdown. Deterministic Event regressions for both paths.
5. **Issue #15** IP-ban cooldown and local-transcribe queue-first contract preserved. Known limitations: `archive_lock` does not coordinate other OS processes accessing `references.md` directly, and discovered Reddit/community-post children may still recurse through old `process_url`. Neither is claimed fixed.

## Release gate

PR #19 remains draft/open and unmerged pending **new, explicit user authorization for issue #18**. The user's earlier approval for issue #15's rollout does not cover this change. When authorized: re-verify actual latest PR SHA and CI, merge by PR, wait for post-merge exact-main-SHA CI; prepare an idle-window minion deploy using `ref-cli[api]` SHA-pinned pipx, verified current archive **and show_notes_queue** backups, API-capable rollback to prior running `799b10f28dd3776a8d9904509d166368e289bb7c`, then post-install `/health`, `ref --status`, `GET /queue`, and bounded logs. Never restore stale archives as ordinary package rollback or force stop in-flight POST. No access to secrets/private SSH keys.

## Exactly one next step

User: authorize (or decline) merge/deployment of QA-approved issue #18 PR #19. OpenCode should **not** run production steps on its own before that user decision.
