# Agent handoff — ref-cli

## Current state
- **INDEPENDENT QA FAILED on SHA `d2b2a028253cbc09dd2dc94b28696ee139b3eafb` despite both green CI runs; corrective task queued.** Original feature is not accepted, merged or deployed.
- Repository: https://github.com/draeician/ref
- Default/protected branch: `main` (unchanged); starting main SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- Development branch: `fix/issue-15-ref-api-disconnect`.
- Task: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`.
- Pointer: `.codex/notes/current-task.md`.
- GitHub issue: https://github.com/draeician/ref/issues/15
- Draft PR: **#16** — https://github.com/draeician/ref/pull/16 (`Fixes #15`).
- Implementation head (all application code/tests/CI/docs, CI **green**): `6c9f2b09e6e6e925fe65836975dc3c39feb5b56f`.
- This handoff commit is docs-only; GitHub Actions were re-verified on the branch tip after its push (see Final SHA / CI below).
- Action taken this handoff cycle: `[CLAIM]` posted on issue #15 (2026-10-14).

## Work completed this handoff cycle
- **Root-caused the HTTP RemoteDisconnected from read-only minion evidence** (no production modification):
  - Service: `pipx venvs/ref-cli` → `/home/draeician/.local/bin/ref-api --host 0.0.0.0 --port 8000`; uvicorn single process; version `1.6.12b1.dev40+g276ea2afd`; `youtube-transcript-api 1.2.4`; unit `Restart=on-failure`, `RestartSec=5`.
  - Journal (pid 1462), exact sequence: `03:05:23 Stopping ref-api.service` (SIGTERM) → uvicorn `Shutting down` / `Waiting for connections to close` → in-flight `POST /urls` for `c6u87wtQzTw` still running its 24-link show-note fan-out at `03:06:23–03:06:31` → `03:06:53 systemd: State 'stop-sigterm' timed out. Killing.` (default `TimeoutStopSec`=90 s) → SIGKILL pid 1462 → socket closed with **no HTTP response** → client `requests` surfaced `RemoteDisconnected('Remote end closed connection without response')`.
  - `systemctl --user show`: `NRestarts=0`, `ExecMainStatus=0`, exit=success → the stop was a deliberate stop/restart (not an auto-restart, not an OOM — no OOM evidence).
  - **Conclusion:** disconnect mechanism = service stopped while a long synchronous request was in flight + graceful-shutdown timeout; the IP block was a **coincident latency amplifier** (639 “blocked transcript requests” WARNINGs on pid 1462, 23:17:38→03:06:48), not the demonstrated cause of the disconnect. Health GET is fast → unaffected.
- **Implemented the user-confirmed, persisted YouTube transcript IP-block cooldown** (task §“Required architect decision”), mandatory per acceptance B:
  - New `src/ref_cli/transcript_block.py`: nonsecret expiry marker `.<transcripts_dir>/.youtube-transcript-block.json` (atomic temp+rename, POSIX `fcntl` lock, in-process memory fallback on persistence failure), default 3600 s, env `REF_YOUTUBE_TRANSCRIPT_BLOCK_COOLDOWN_SECONDS` or config key `youtube_transcript_block_cooldown_seconds`; `is_blocked` / `probe_guard` / `enter_block` (no extension while active, one transition WARNING with expiry+duration+guidance) / `clear_block` / `cooldown_message`.
  - `src/ref_cli/cli.py`: single gate `_youtube_transcript_blocked_skip` before any `youtube-transcript-api` call (enhanced **and** legacy) that returns a `("blocked", …)` failure → existing queue-first / `transcript-pending.md` fallback runs unchanged; four `log_blocked_warning` sites replaced by `_note_youtube_transcript_blocked`; two success returns call `clear_block` (probe success resets); metadata (YouTube Data API) and show-note discovery untouched.
- **Tests (`tests/test_transcript_block.py`, 23)**: first block sets cooldown + exactly one warning; subsequent videos skip provider + no repeated warning; expiry→probe→success clears; probe→re-block renews; concurrent enter_block converges (no extension, 8 threads); persistence across fresh module state; corrupt marker ignored; env/config duration; no false trigger for missing captions; disk transcript kept/not enqueued; queue-first (`enqueued`) and pending-file fallback preserved; CLI + API (`service.process_one`, `POST /urls` and `GET /health`) paths. API tests stub fake-video enrichment so they never depend on network.
- **CI gate**: `.github/workflows/tests.yml` (push on `fix/issue-15-ref-api-disconnect` + `pull_request`, Python 3.12, `pip install -e ".[api,test]"`, `python -m pytest -q`). Fixed `httpx2` → `httpx` in the `[test]` extra (TestClient dependency).
- **Docs**: `README.md` “YouTube transcript IP-block cooldown” section (behavior, config, marker path, manual reset).

## Changed areas (concrete)
- `src/ref_cli/transcript_block.py` (new)
- `src/ref_cli/cli.py` (cooldown gate + hook, 4 block sites, clear-on-success)
- `tests/test_transcript_block.py` (new, 23 tests)
- `.github/workflows/tests.yml` (new)
- `pyproject.toml` (`httpx2` → `httpx`)
- `README.md` (cooldown docs)
- This handoff (docs)

## Important decisions / invariants
- Disconnect diagnosis separated from cooldown requirement: the IP ban did **not** cause the connection drop; it made requests long enough that a graceful stop could not drain.
- Smallest repair for the disconnect is bounding the transcript latency class (cooldown) so `POST /urls` returns bounded results; the stop-in-flight disconnect itself is an operator/service-lifecycle issue requiring a production change (not authorized here) — recorded as an open production validation gate (C) and a documented operator remedy (stop only drains after in-flight sync requests; raised `TimeoutStopSec` or draining before restart).
- Write lock across network work is preserved (safe-separation analysis deferred, not casually unlocked).
- Contracts preserved: `POST /urls` schema/status labels, 50-link cap, nonrecursive discovery, normal CLI mode, skip/security rules, idempotent archive writes, local-transcribe `enqueued`/`existing_active`/`requires_force`/pending fallback. No credentials in logs.
- No scheduler/queue, proxy bypass, or speculative refactor.

## Verification performed (exact)
- Python 3.12.3; fresh `.venv` in a dedicated worktree (`/tmp/opencode/ref-issue-15`).
- Focused: `python -m pytest tests/test_transcript_block.py tests/test_transcript_blocking.py tests/test_api.py tests/test_youtube_api_notes.py tests/test_api_client.py` → **99 passed**.
- Full: `python -m pytest -q` → **307 passed** (284 baseline + 23 new).
- `python -m compileall -q src get_transcript.py` → OK.
- No Aether/uv/ruff/mypy gates exist for this repo (not claimed).
- GitHub Actions: green on implementation head `6c9f2b09e6e6…` (push run 38514022852 + PR run 38514026839). Earlier red runs on `69b84d6` were fixed by adding fake-video enrichment stubs (the test had depended on network-facing enrichment that drops non-real videos).

## Known issues / risks
- Cross-process probe stampede at exact expiry is mitigated by atomic marker + process-local lock only; a distributed probe lease needs a scheduler/control plane (deferred).
- Marker persistence failure degrades cooldown to in-process for that run (documented in module + README).
- Live production validation (gate C) open: demonstrating the fix on the live service would require stopping/restarting `ref-api.service` (not authorized from this branch).
- Enrichment of non-real videos deletes rows (existing behavior, unrelated); cooldown tests stub it.
- API remains unauthenticated (trusted network only); SSRF DNS/redirect hardening deferred.

## Deferred work
- Async/durable ingest architecture (replace synchronous `POST /urls`), full SSRF hardening, proxy/VPN rotation, deeper packaging/linters, deployment and merge to `main` (require user authorization).

## Final SHA / CI status
- Implementation head: `6c9f2b09e6e6e925fe65836975dc3c39feb5b56f` — pytest **green** (push + PR workflows).
- Branch tip at handoff time (this docs commit) is re-verified green after push; exact tip SHA reported in `[REVIEW-REQUEST]`/PR.

## Independent architect QA — 2026-10-14
- Compared `main` at `276ea2afd` to PR #16 head `d2b2a028253cbc09dd2dc94b28696ee139b3eafb`: nine changed files, no unrelated WIP files, main unchanged, PR remains draft. Reviewed actual `src/ref_cli/transcript_block.py`, `src/ref_cli/cli.py`, `tests/test_transcript_block.py`, CI workflow and task docs.
- GitHub Actions completed SUCCESS on **exact SHA** `d2b2a028253cbc09dd2dc94b28696ee139b3eafb` for push run 38514600822 and PR run 38514605728, each with `307 passed`. This verifies CI state, not the correctness of the untested concurrency path.
- **FAIL:** `cli.py:_youtube_transcript_blocked_skip` exits `probe_guard` before external transcript retrieval begins; `probe_guard` only uses a thread-local lock and never holds ownership across provider I/O. On expiry multiple callers/processes may independently probe. Marker-write concurrency test does not cover this.
- **FAIL:** `clear_block` executes on any successful transcript retrieval, so an older in-flight success can erase a more recently recorded block by another caller. Must guard clear by lease/block epoch ownership.
- **FAIL:** `_read_marker_unlocked` can raise on malformed numeric `set_at` / `duration_seconds` fields after successful JSON parse, breaking best-effort capture. Add a safe parse and test.
- **Accuracy correction:** A reported operator/systemd SIGTERM followed by timeout SIGKILL is consistent with `RemoteDisconnected`; architect did not independently access live minion journal. No shutdown/service code changed in PR. Block suppression mitigates one latency source but does not guarantee `POST /urls` returns before service stop. Live deployment/validation remains open pending separate authorization.
- New scoped corrective task: `.codex/tasks/e6c9124b-issue-15-probe-ownership-correction.md` and canonical pointer updated. Original issue/task not complete. This planning update itself changes branch HEAD and must be included in next exact-SHA CI verification.

## Exactly one recommended next step
OpenCode: implement `.codex/tasks/e6c9124b-issue-15-probe-ownership-correction.md` on the existing `fix/issue-15-ref-api-disconnect` branch/PR #16, add deterministic threaded and cross-process probe-ownership tests, update handoff and PR claims, push and verify green push+PR workflows on the new final SHA, and request independent re-review.

## Local/working-tree notes
- Implementation was done in a dedicated git worktree; production checkout at `/home/draeician/git/personal/ref` was NOT touched (its modified `TODO.md` and untracked `BAD`, `advisors.md` remain intact).
- WIP marker created at `/tmp/opencode/wip-marker-issue-15.txt` before repository actions; nothing ephemeral was committed.
