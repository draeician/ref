# Agent handoff — ref-cli

## ACTIVE — Issue #18: QA corrections implemented, awaiting re-review (PR #19)

- **Status:** All five architect blocking defects are **corrected** in commit `559767654a117dcc20564a3f4f39ab321476d20e` on `fix/issue-18-youtube-show-notes-timeout`. Awaiting independent architect QA; **not merge/deploy-approved**. Reviewed-but-rejected SHA was `2b0fba7e64888ce14a700281379a0de0778baf54`; `main` remains `799b10f28dd3776a8d9904509d166368e289bb7c`.
- **Canonical correction task:** `.codex/tasks/7e4c9b12-issue-18-qa-corrections.md` (IMPLEMENTED). Original task `.codex/tasks/d0c54a91-issue-18-youtube-show-notes-timeout.md` is IN-REVIEW. `.codex/notes/current-task.md` points to this.
- **Corrections (one per defect):**
  1. **Concurrency** — `src/ref_cli/cli.py` gained `_archive_lock` (RLock) wrapping only short archive read/write primitives; `service.py` aliases `_write_lock = ref_cli._archive_lock` and no longer holds it across `process_url`, so slow provider/transcript I/O runs outside the lock. Global `redirect_stdout` replaced by a thread-local stdout proxy. Regression `test_worker_slow_child_does_not_block_new_ingest` proves a second `POST /urls` returns <5s while the worker is blocked in a slow child.
  2. **Discovery off the parent path** — `process_one` enqueues a `discover` job; `_process_discovery_job` fetches the card and batch-enqueues `ingest` jobs. Regression `test_parent_returns_before_slow_discovery` blocks uncached `read_video_card` on an Event; parent returns `added` + `discovery queued` before release.
  3. **Fail-closed queue** — corrupt/unreadable/schema-invalid `jobs.json` raises `QueueCorruptError`, preserves original bytes, and surfaces via new `/queue` `corrupt` field. Regressions `test_corrupt_jobs_file_fails_closed`, `test_schema_invalid_job_fails_closed`.
  4. **Bounded history + dedup** — `enqueue` skips `pending/running/done` (failed may retry), terminal history compacted to `MAX_TERMINAL_JOBS`, children batch-enqueued via `enqueue_many`. Regressions `test_enqueue_skips_completed_work`, `test_failed_job_can_be_reenqueued`, `test_terminal_history_is_bounded`, `test_enqueue_many_batches_and_dedupes`.
  5. **Worker lifecycle fence** — `stop()` returns whether the thread exited; `stop_show_notes_worker` leaves the singleton set during a slow drain so `start()` cannot spawn a duplicate. Regression `test_worker_stop_fence_prevents_overlap`.
- **Evidence:** `python -m pytest -q` → **362 passed** (355 prior + 7 new); `compileall -q src tests` OK; `git diff --check` clean (Python 3.12.3, venv `/tmp/opencode/ref-issue-18-venv`).
- **Preserved:** issue #15 IP-block cooldown and local-transcribe queue-first contract, direct-playlist full expansion, discovered-playlist link-only recording, `references.md` integrity, `added/exists/skipped/error` semantics, 50-link cap and safe-link filtering. No production mutation or merge.
- **Operator incident (unchanged):** production `ref-api` healthy at `g799b10f28`; original YouTube parent recorded, 20 show-note links; ~8-minute pause across one playlist child; client read timeout 300s; cooldown active as expected. Latest PR not installed in production.

## Exactly one recommended next step

OpenCode: push `fix/issue-18-youtube-show-notes-timeout`, update draft PR #19 body, verify GitHub PR CI on the exact final remote SHA, then return `[REVIEW-REQUEST]` for independent architect QA.

## Archived issue #15 history (historical, may contain superseded state assertions)

## Current state
- **IMPLEMENTATION QA PASSED** on exact reviewed SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d` for issue #15 cooldown and all probe corrections. **CUTOVER PREFLIGHT QA previously BLOCKED on unsafe package rollback instructions is now CORRECTED (task c41e90b7):** rollback targets the prior API-capable SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee` (never pre-API `ref-cli==1.6.11`), the SHA-pinned `ref-cli[api]` pipx install/rollback was verified in an isolated temporary pipx environment, and archive data is preserved by default. Draft PR #16 is NOT merged/deployed. The user has conditionally authorized the eventual merge+deploy; independent review, post-merge main-SHA CI, and idle-window production cutover remain OPEN.
- Repository: https://github.com/draeician/ref
- Default/protected branch: `main` (unchanged); baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- Development branch: `fix/issue-15-ref-api-disconnect`.
- Draft PR: **#16** — https://github.com/draeician/ref/pull/16 (`Fixes #15`), re-titled to emphasize the transcript cooldown (no disconnect-hardening implication).
- Correction tasks: `5f46ca91` (current, authoritative for this cycle) → `e6c9124b` (prior) → `b3e718cf` (original spec).
- Handoff: this file; pointer: `.codex/notes/current-task.md`.

## Work completed this cycle (task 5f46ca91 — three narrow defects)
All in `src/ref_cli/transcript_block.py` + `tests/test_transcript_probe_concurrency.py`:

1. **Stale unrelated FAIL no longer perturbs a newer owner/epoch.**
   - `finish_probe` now computes `_owns_current_epoch(marker)` = `lease_owner == decision.owner` **and** `blocked_until == decision.epoch_blocked_until`, and only then may clear (success) or release-lease-and-arm-backoff (unrelated failure/abort). A stale finish from an older probe leaves the newer marker entirely untouched: it cannot seize another owner's lease, cannot overwrite a newer block epoch, and cannot arm a backoff on someone else's behalf.
   - Confirmed-block precedence is unchanged: blocked results always (re)enter the cooldown (never extend an active one) and release only the caller's own lease slot.

2. **Numeric-overflow marker parse.**
   - `_as_finite_nonneg` (used for `blocked_until`, `set_at`, `lease_expires_at`, `next_probe_at`) now catches `OverflowError` in addition to `TypeError`/`ValueError`, so a huge-but-valid JSON integer (e.g. 400 digits) is treated as malformed → never raises into capture. `_as_int_nonneg` (duration) already caught it.

3. **Atomic process-local lease claim when POSIX locking/persistence unavailable.**
   - Added `_process_state_lock = threading.RLock()`, always held inside `_file_lock` around marker read/modify/write. So even when `fcntl` import / `makedirs` / lock-file open / `flock` fails (or the marker cannot be persisted and only the in-memory fallback is available), two threads starting together still get exactly one process-local recovery owner; the other is denied and routes to queue/fallback. Never held across provider I/O (`begin_probe`/`finish_probe` only hold it around state transitions).

## Regression evidence (fail at reviewed SHA → pass after fix)
Reviewed implementation: `669c692d4b98526cb86167a679be8acdf7cd2b33` (branch tip `f06eb81` = same app code + architect doc commits).

Ran new tests against reviewed `transcript_block.py` via `git stash` and captured failures:
- `test_stale_unrelated_failure_cannot_alter_newer_owner_or_lease` → **FAILED** on reviewed (stale fail seized B's lease/armed backoff)
- `test_stale_failure_after_new_epoch_cannot_edit_marker` → **FAILED**
- `test_huge_valid_json_number_never_throws[blocked_until|set_at|lease_expires_at|next_probe_at]` → **FAILED** (OverflowError: int too large to convert to float)
- `test_process_local_single_flight_without_posix_lock_or_persistence` → **FAILED** (two threads both claimed with flock+persistence forced unavailable; barrier + slowed commit make the race deterministic on the lock-less build)

After correction: all new tests pass; full suite green.

## Verification (exact commands/results, Python 3.12.3, worktree `/tmp/opencode/ref-issue-15`)
- Focused: `python -m pytest tests/test_transcript_block.py tests/test_transcript_probe_concurrency.py tests/test_transcript_blocking.py tests/test_api.py tests/test_youtube_api_notes.py tests/test_api_client.py -q` → **128 passed**
- Full: `python -m pytest -q` → **336 passed** (326 prior + 10 new)
- `python -m compileall -q src get_transcript.py` → OK
- `git diff --check` → clean

## Changed files (exact)
- `src/ref_cli/transcript_block.py` — `_process_state_lock` + `_file_lock` rework; `_as_finite_nonneg` OverflowError; `finish_probe` `_owns_current_epoch` guard on success/failure paths.
- `tests/test_transcript_probe_concurrency.py` — 10 new deterministic regression tests (2 stale-fail, 1 stale-success-after-new-owner, 6× huge-number params, 1 process-local-without-lock/persistence with barrier+slow-commit).
- `.codex/notes/agent-handoff.md`, `.codex/notes/current-task.md` — this cycle's status.
- PR #16 title/body re-worded (no disconnect-hardening claim; evidence of observed shutdown retained; production cutover gate marked open).

## Known issues / risks
- Cross-process single-flight relies on the atomic marker + file lock (no distributed lease beyond the bounded window) — documented.
- Persistence failure degrades cooldown/lease to process-local for the affected process only; cross-process suppression then degenerates (documented).
- Live production validation (stop-in-flight disconnect, real ban recovery on minion) remains OPEN and is explicitly not claimed; requires authorized operator action.
- API remains unauthenticated (trusted network only); SSRF DNS/redirect hardening deferred.

## Deferred work
- Async/durable ingest architecture, full SSRF hardening, proxy/VPN rotation, deeper packaging/linters, deployment and merge to `main` (require user authorization).

## Architect independent PASS review — 2026-10-14

- **QA verdict:** PASS for implementation and regression coverage on **exact** `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d`. `main` remained unchanged at `276ea2afdfd8ea401f1849ba50b847225487f9ee`, and PR #16 remained open/draft, targeting main. No merge or deploy performed. Examined actual changed `src/ref_cli/transcript_block.py`, `src/ref_cli/cli.py`, test suite, task/handoff, workflow, and relevant API/service architecture.
- **Remedies verified by source/tests:** `finish_probe` non-block completion now changes marker only when matching both current `lease_owner` and `epoch_blocked_until`; stale failures/successes cannot take over new owner/epoch. `_as_finite_nonneg` now catches `OverflowError` for huge valid JSON numbers. `_file_lock` wraps state transitions in a process-local `RLock` even when POSIX file locking fails; no state lock held across provider I/O. Existing cross-process single-flight and queue-first integration tests retained.
- **Exact-SHA remote CI independently VERIFIED SUCCESS**: push run https://github.com/draeician/ref/actions/runs/38619727048, PR run https://github.com/draeician/ref/actions/runs/38619733660, both on the exact reviewed SHA and both direct job logs report **336 passed, 1 warning**.
- **Branch/WIP safety:** PR diff contains only task planning docs, README, pyproject, tests workflow, cooldown module, CLI, relevant tests. No untracked local WIP items appear in committed diff. `main` not advanced.
- **Scope limitation:** API still uses synchronous 50-link show-note fanout and systemd can terminate an in-flight POST; YouTube cooldown mitigates transcript ban request storms, not `RemoteDisconnected` caused by service stop. The implementer provided minion shutdown evidence; architect did not independently access private live minion journal. Live production validation and operator-initiated service actions remain a distinct, unapproved cutover gate.
- **Next-gate discovery:** `.github/workflows/tests.yml` currently runs on PRs and feature-branch pushes only, not **pushes to `main`**. Add main push CI before any merger so project rule requiring post-merge exact-default-branch SHA CI can be satisfied. Also establish read-only minion deployment preflight and rollback procedure rather than assuming `pipx upgrade` will fetch unreleased code.
- **New active canonical task:** `.codex/tasks/a92d761e-issue-15-cutover-preflight.md`; `.codex/notes/current-task.md` now points to it. Feature implementation is QA-approved, not yet merged/production-accepted. The planning commits after the code SHA must themselves receive exact-SHA remote CI when code branch is finalized.

## Cutover preflight (task a92d761e) — read-only, verified 2026-10-14

**Status: main-push CI trigger added; read-only minion preflight COMPLETE. No merge, deploy, restart, install, or unit change performed.** All preflight commands were observational only (status/show/cat, bounded journal, pipx metadata, version/health, archive metadata, free space), sanitized, and excluded secrets and archive contents.

### Service configuration (minion)
- `ref-api.service` user unit: `Type=simple`, `ExecStart=/home/draeician/.local/bin/ref-api --host 0.0.0.0 --port 8000`, `EnvironmentFile=-/home/draeician/.config/ref/ref-api.env` (file present, no active vars), `Restart=on-failure`, `RestartSec=5`, `WantedBy=default.target`. **No `TimeoutStopSec` override** — effective `TimeoutStopUSec=1min 30s` (systemd default).
- State: `active (running)` 17h, `MainPID=6083`, `NRestarts=0`, `Result=success`, `ExecMainStatus=0`, enabled. One `Started ref-api.service` in last 24h (03:06:53, i.e. the restart after the documented stop-timeout kill). No error-level journal entries beyond routine per-URL `Lynx command timed out` messages during show-note fanout.

### Installed package source (verified, NOT released code)
- `pipx list` → `ref-cli 1.6.12b1.dev40+g276ea2afd.d20261010`, apps incl. `ref`, `ref-api` under `~/.local/bin`.
- `src/ref_cli/_version.py` is git-ignored (setuptools_scm generated); installed dist-info `direct_url.json` = `{"dir_info": {}, "url": "file:///opt/md2/git/personal/ref"}` with **no** `__editable__`/`.pth` marker → **non-editable local-directory install**.
- `ref --version` / `/health` both report `1.6.12b1.dev40+g276ea2afd.d20261010` (main `276ea2afd`, 40 commits past `v1.6.12-beta`, dirty build). Production checkout `/home/draeician/git/personal/ref` = `main` @ `276ea2a`.
- The running process still logs per-video `YouTube blocked transcript requests` warnings (e.g. 20:38–20:39 UTC) → the approved cooldown fix is **not yet active in production**, exactly as expected before cutover. Production artifact provenance: `pipx install file:///opt/md2/git/personal/ref`.

### Service lifecycle / disconnect distinction (preserved)
- Working, tested: transcript **cooldown** suppresses remote transcript calls during a confirmed IP block and persists a cross-process marker at `<transcripts_dir>/.youtube-transcript-block.json`.
- **NOT resolved by this feature:** stopping `ref-api.service` while a synchronous `POST /urls` is in flight (show-note fanout can run minutes) → 90s graceful stop timeout (`TimeoutStopUSec=1min 30s`) → systemd SIGKILL closes the socket with **no HTTP response** → client `RemoteDisconnected`. Observed in journal (03:05:23 stop → 03:06:53 SIGKILL). Cooldown reduces the request-storm amplifier, not stop-in-flight disconnects. Production validation of this gate remains open and operator-authorized only.

### Backup verification (read-only)
- `~/references` = 638M. Snapshot/backup evidence present: `references.md.bak-20260717T203644.gz` plus timestamped gzip snapshots `YYYYMMDDTHHMMSS_references.md.gz` in the archive root, and a `backups/` subdir. `ref --backup` writes/gzips a timestamped copy (local mode uses the file directly when `api_url` is loopback).
- Cooldown marker `~/references/transcripts/.youtube-transcript-block.json` does **not** exist yet (old code never writes it) — expected pre-cutover. Disk: 4.0T (6% used, 3.6T free).

### Actual deployment procedure (documented; SHA-pinned `[api]` install verified in isolated temp pipx; NOT executed on production; requires explicit operator authorization)
Do **not** assume `pipx upgrade ref-cli` reaches the unreleased GitHub branch — the pipx metadata points at a local directory snapshot (`file:///opt/md2/git/personal/ref`), and PyPI has no matching release. Use the SHA-pinned, `[api]`-inclusive VCS spec below (verified in an isolated throwaway `PIPX_HOME`, never production). One command installs the package **and** its FastAPI/uvicorn extras (no separate `pipx inject` needed):
1. **Snapshot (disaster-recovery only, optional):** `ref --backup` and note the new gzip under `~/references`. Do NOT plan to restore this during a normal code rollback.
2. **Code phase-in:** `pipx install --force 'ref-cli[api] @ git+https://github.com/draeician/ref.git@<final-sha>'`, then confirm `pipx list` / `ref --version` shows the new SHA-derived version and that `ref-api --help` exits 0.
3. **Unit unchanged** (no `systemctl --user cat` change needed); `systemctl --user daemon-reload`, then `systemctl --user restart ref-api.service` **only in the idle window** (no in-flight POST).
4. **Verify:** `systemctl --user status ref-api` active; `curl -sS http://127.0.0.1:8000/health` = `{"status":"ok","version":"…<new-sha>…"}`; `ref --status` ok; confirm first confirmed block creates `~/references/transcripts/.youtube-transcript-block.json`; during bloom, expect suppressed remote transcript calls and no per-video ban warnings.
5. **Rollback (API-capable; archive-preserving):** `systemctl --user stop` only in an idle window; `pipx install --force 'ref-cli[api] @ git+https://github.com/draeician/ref.git@276ea2afdfd8ea401f1849ba50b847225487f9ee'` (the prior **API-capable** revision — verified to restore a working `ref-api`); `systemctl --user restart ref-api.service`; re-verify `/health` + `ref --status`. **Do NOT** roll back to `ref-cli==1.6.11` — README documents it as the last **pre-API** PyPI release and it lacks `ref-api`. Application rollback **does not touch `~/references`**; the archive is preserved by default. Restoring `references.md` from `references.md.bak-*.gz` / `*_references.md.gz` is **disaster recovery only** (proven corruption) and will discard entries written after the snapshot.
Standalone caveats to record in the cutover execution ticket: synchronous 50-link fanout and long per-URL network work mean a single POST is unbounded; schedule restarts when no client POST is active; API remains unauthenticated (trusted network only).

## Cutover safety correction (task c41e90b7) — isolated pipx verification 2026-10-15

Blocking finding from architect review of a92d761e: the prior rollback advised pre-API `ref-cli==1.6.11` (would remove `ref-api`); `pipx install --force` from VCS was not proven to retain the `[api]` extras; and routinely restoring an old `references.md` backup risks losing post-snapshot entries. Corrected and verified without touching production:

- **Production install provenance (read-only, minion):** pipx `ref-cli 1.6.12b1.dev40+g276ea2afd.d20261010` base (non-editable local-dir `file:///opt/md2/git/personal/ref`) **plus** injected `ref-cli 1.6.12b1.dev15+g5642e2e44`; venv contains fastapi 0.143.0 / uvicorn 0.54.0; `ref-api` entry point present; `~/references` 644M intact.
- **Isolated smoke test** (dedicated temp `PIPX_HOME` + `PIPX_BIN_DIR` under `/tmp`, never the production pipx home/archive/service; dir removed after):
  - `pipx install 'ref-cli[api] @ git+https://github.com/draeician/ref.git@3626d65bc2b61dc2d076ded878d23314fccf22dc'` → `ref 1.6.12b1.dev77+g3626d65bc`; `ref-api --help` exit 0; baked venv imports `fastapi 0.143.1`, `uvicorn 0.54.0`, `ref_api.app` → OK.
  - `pipx install --force 'ref-cli[api] @ git+https://github.com/draeician/ref.git@276ea2afdfd8ea401f1849ba50b847225487f9ee'` → `ref 1.6.12b1.dev40+g276ea2afd` (matches production baseline); `ref-api --help` exit 0; API imports OK.
  - **Conclusion:** `ref-cli[api] @ git+…@<sha>` installs package + FastAPI/uvicorn in one step (no separate `pipx inject`), and the same spec pinned at the prior SHA is a working API-capable rollback. GitHub was reachable from minion.
- **Archive safety:** package rollback replaces only the pipx venv; `~/references` is untouched. Old `references.md` backups are disaster recovery only, with an explicit post-snapshot data-loss warning.

## Architect independent preflight QA — 2026-10-14

- **Verdict:** a92d761e CI portion PASS, **cutover plan FAIL** pending narrow correction. Reviewed exact PR HEAD `5747ff15aaaad1df998c3dae750d5f82bb24d090` (same as development branch), `main` untouched at `276ea2afd`, PR #16 draft/unmerged. Since last accepted code only workflow `.github/workflows/tests.yml` and canonical docs changed; no unapproved app modifications.
- **Remote exact-SHA CI verified:** push https://github.com/draeician/ref/actions/runs/38635883999 and PR https://github.com/draeician/ref/actions/runs/38635892439, both completed SUCCESS at the exact reviewed SHA, with **336 passed** in each job log. Workflow now includes `main` in push branches. Architect has **not** independently connected to minion; read-only service/pipx/backup evidence is implementer's report; the report is consistent with repo architecture.
- **Blocking deployment/rollback safety correction:** current handoff and PR body advise `pipx install --force 'ref-cli==1.6.11'` as a fallback, but this repository's README explicitly identifies 1.6.11 as **before** ref-api existed. Restoring it would remove the live API capability. Must roll back to actual pinned API-capable baseline `276ea2afdfd8ea401f1849ba50b847225487f9ee`, not 1.6.11. `pipx install --force` may also drop separately injected `[api]` dependencies; exact SHA-pinned `[api]` syntax and resulting `ref-api`/FastAPI/uvicorn availability must be tested in an isolated throwaway pipx environment before deployment. Routine `references.md` backup restore as part of package rollback risks discarding post-snapshot references; preserve archive by default and restore data only on proven corruption with explicit data-loss assessment.
- **New canonical corrective task:** `.codex/tasks/c41e90b7-issue-15-pipx-cutover-safety.md`; `.codex/notes/current-task.md` points to it. This is documentation/isolated packaging verification only. No production deploy, merge or restart authorized. Previous app-code QA remains accepted.
- **Release/incident gate still open:** cooldown mitigates YouTube transcript IP ban requests; it does NOT fix systemd SIGKILL of long synchronous in-flight POST. Production validation remains operator-authorization-gated.

## Explicit user merge/deploy authorization — 2026-10-14

- User: "Then let's push it to main and get it in production if it's ready." This is **conditional authorization** to merge PR #16 and deploy, not evidence that it is ready. **DO NOT bypass** current `c41e90b7` failed release-safety gate. Last checked code remains QA-passed; latest reviewed feature branch `80e306e15c294a5d4973ab48e85efe9c077a770e` had green push/PR CI, but the documented rollback still targets pre-API `ref-cli==1.6.11` and the SHA-pinned pipx `[api]` install/rollback has not been smoke-tested. Recheck SHA after this documentation commit.
- This architect does not have direct access to minion and network access in the isolated container cannot resolve GitHub, so isolated pipx smoke and production cutover must be performed by OpenCode on minion, with read-only/staged work first.
- **Execution boundary:** OpenCode completes the existing `c41e90b7` correction and returns `[REVIEW-REQUEST]`, including actual isolated install/rollback evidence and exact final SHA/CI; architect independently reviews and merges via PR after successful gates; after exact-merged-main-SHA CI green, OpenCode may perform operator-authorized **idle-window production cutover** following proven procedure with backups and preserved archive data, then return installation SHA/version, `/health`, `ref --status`, cooldown/queue behavior and journal evidence. Stop and report if the host is busy or any gate fails. No extra confirmation needed for the already-approved overall goal.
- **No user SSH-key inspection** or secret disclosure required.


## Local/working-tree notes
- Dedicated worktree `/tmp/opencode/ref-issue-15`; production checkout `/home/draeician/git/personal/ref` untouched (modified `TODO.md`, untracked `BAD`, `advisors.md` intact).
- WIP markers: `/tmp/opencode/wip-marker-issue-15.txt`, `-v2.txt` … `-v6.txt` (`2026-10-15T00:27:51Z`); no ephemeral files committed. Isolated smoke dir was under `/tmp` and was removed.
