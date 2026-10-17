# Current task — ref-cli

- **State:** NEW PRODUCTION LATENCY BUG **#18 OPEN**, root cause strongly localized to synchronous YouTube show-note child fan-out; **no new fix coded or deployed**. OpenCode implementation + draft PR required; independent architect QA before merge.
- **Canonical task:** [d0c54a91 — bounded, reliable YouTube show-note child processing](../tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md).
- **Issue:** https://github.com/draeician/ref/issues/18
- **New isolated implementation branch:** `fix/issue-18-youtube-show-notes-timeout`, created from merged `main` `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Draft PR:** Not yet opened; OpenCode to open ONE draft PR to `main` with `Fixes #18`.
- **Canonical agent handoff:** [agent-handoff.md](agent-handoff.md) (latest section at top; archived issue #15 history below).
- **Previous release:** issue #15 cooldown code merged with PR #16 on main commit `799b10f28dd3776a8d9904509d166368e289bb7c`; post-merge CI passed 336 tests; issue #17 tracks the operational deployment. On 2026-10-16 the operator's `ref --version` and `/health` **both** reported `1.6.12b1.dev79+g799b10f28`, proving new cooldown code active in running production. Operator journal observed exactly one 3600-second cooldown after an IP block.

## Verified issue #18 evidence

- User on `minion` ran `ref https://www.youtube.com/watch?v=cB4d7KHIyNc`: `ref API at 127.0.0.1:8000 did not respond in time (read timeout)`. CLI default POST timeout: **300 seconds**.
- `/health` still OK, `ref-api.service` active/running, `MainPID=10853`, `NRestarts=0`; archive contains **one** match for video ID. A client timeout therefore did not prevent parent recording.
- At `2026-10-17T02:42:12Z`, 20 show-note outbound URLs discovered; 14 children completed by `02:42:52Z`; next completion at `02:50:55Z` was a **playlist link** after an ~8-minute gap; notes completed `02:51:08Z` (20 processed, 20 already existed, zero errors). IP cooldown activated at `02:50:54Z` (3600 sec), demonstrating the previous fix works.
- Source: `src/ref_api/service.py` `process_one` synchronously triggers `_process_youtube_show_notes` even for already-recorded parents; that loops children inline before returning the HTTP response. `_discover_youtube_links=False` disables recursive show-note discovery but **not** full `ref_cli.process_url` playlist traversal for discovered children.
- **Hypothesis:** slow discovered playlist child caused the gap; verify deterministically in code/tests. Root cause of HTTP latency is established (synchronous child work), not every underlying individual network operation.
- This is a distinct bug from issue #15's transcript-ban cooldown AND the previously observed `RemoteDisconnected` when systemd kills an in-flight POST.

## Agent / authorization boundary

OpenCode owns code. Use isolated worktree, WIP marker outside repo, preserve user local WIP. Write deterministic regressions and a bounded, crash-recoverable queue/continuation for child URLs (or documented equivalent), no silent dropping, parent returns without waiting; keep direct playlist semantics. Full tests+compile+diff check, one draft PR, exact-SHA CI, then independent architect review. **No direct push to main, production pipx changes, systemd restart, archive edits, live test ingest, or secret inspection for issue #18** without a separate approval. Historical authorization for issue #15 deployment does **not** authorize an unrelated #18 deployment.

## Exactly one next step

OpenCode: implement canonical task `d0c54a91` in the existing isolated feature branch and return a draft PR `[REVIEW-REQUEST]` with exact-SHA source/tests/CI evidence.
