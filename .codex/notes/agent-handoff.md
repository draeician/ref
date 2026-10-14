# Agent handoff — ref-cli

## Current state
- **INDEPENDENT IMPLEMENTATION QA PASSED** on exact reviewed SHA `dfb8b50733f21e0fdbbb6d07131ea5a5fa7ab35d` for issue #15 cooldown and all probe corrections. Draft PR #16 is NOT merged/deployed. Post-merge CI, production validation, and cutover remain OPEN and require explicit user authorization.
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

## Exactly one recommended next step
OpenCode: on the existing development branch/PR #16, complete `.codex/tasks/a92d761e-issue-15-cutover-preflight.md` (add main-push CI trigger and read-only cutover/rollback preflight, no application code or production mutations), update this handoff, push and verify both remote workflows on the final exact SHA, and request independent review.

## Local/working-tree notes
- Dedicated worktree `/tmp/opencode/ref-issue-15`; production checkout `/home/draeician/git/personal/ref` untouched (modified `TODO.md`, untracked `BAD`, `advisors.md` intact).
- WIP markers: `/tmp/opencode/wip-marker-issue-15.txt`, `-v2.txt`, `-v3.txt`; no ephemeral files committed.
