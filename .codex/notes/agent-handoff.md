# Agent handoff — ref-cli

## Current state
- **QA FAILED on reviewed SHA `d2b2a028253cbc09dd2dc94b28696ee139b3eafb`; probe-ownership correction IMPLEMENTED on the same branch/PR #16; awaiting independent re-review. Not merged, not deployed, not accepted.**
- Repository: https://github.com/draeician/ref
- Default/protected branch: `main` (unchanged); starting main SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- Development branch: `fix/issue-15-ref-api-disconnect`.
- Draft PR: **#16** — https://github.com/draeician/ref/pull/16 (`Fixes #15`), body corrected to honestly separate (a) tested transcript cooldown from (b) un-fixed systemd stop-in-flight HTTP disconnect.
- Corrective task: `.codex/tasks/e6c9124b-issue-15-probe-ownership-correction.md` (authoritative for this cycle).
- Incident: https://github.com/draeician/ref/issues/15 (claimed; [REVIEW-REQUEST] re-posted).

## Corrective work completed this cycle (issue 15 QA findings)
1. **Cross-process single-flight recovery probe lease** (`src/ref_cli/transcript_block.py`):
   - `begin_probe(transcripts_dir)` / `finish_probe(...)` with a bounded ownership lease stored in the same atomic marker file, guarded by the short `fcntl` state lock. Exactly one caller (thread OR OS process) owns the recovery probe after cooldown expiry; everyone else is skipped and routed to the queue-first / `transcript-pending.md` fallback. No marker ⇒ routine operation, no lease ⇒ normal concurrent downloads are never serialized.
   - Lease is bounded (`PROBE_LEASE_SECONDS = 300`) so a crashed owner cannot wedge ingestion; stale leases are reclaimed. Unrelated (non-block) probe failures release the lease and arm a bounded probe backoff (`PROBE_BACKOFF_SECONDS = 60`); eventual recovery without stampede.
   - Never holds the file lock across network calls; persistence failure degrades to in-process (memory) marker/lease, never fails capture.
   - **Epoch/owner-aware clearing:** only the current lease owner may clear, and only when the marker was not renewed behind it. A stale success can never erase a newer cooldown; a confirmed block always takes precedence (never extends an already-active cooldown; one transition WARNING per epoch).
2. **`cli.py` restructure:** YouTube provider body extracted to `_fetch_youtube_transcript_provider`; the probe scope (begin/finish) wraps the entire provider call so ownership is held across the provider I/O; single `finish_probe` call site for every outcome (success/blocked/unrelated); **cooldown re-checked before the enhanced→legacy fallback** so another process's fresh block is never bypassed; unexpected exceptions are treated as unrelated failures (lease released + backoff).
3. **Hardened marker parsing:** `_read_marker_unlocked`/`_as_*` handle malformed JSON, NaN/infinity (incl. `OverflowError` on `int(inf)`), non-numeric fields, and implausible timestamps (> year ~2100) without ever throwing into API capture (returns "not blocked").
4. **Docs/claims corrected:** README + PR #16 + current-task no longer claim the cooldown guarantees bounded `POST /urls` or fixes systemd stop-in-flight `RemoteDisconnected`. The observed disconnect (SIGTERM 03:05:23 → graceful-shutdown wait → TimeoutStopSec SIGKILL 03:06:53 → socket closed with no response) is recorded as an observed operator/service-lifecycle mechanism; live production validation remains an OPEN separate cutover gate.

## Root-cause distinction (kept precise)
- **Cooldown purpose:** reduce YouTube transcript request load and repeated IP-ban warnings during a confirmed block; it is implemented and tested here.
- **HTTP RemoteDisconnected:** observed mechanism is an operator-initiated/stop-in-flight service termination; NOT fixed here; can still recur on a future stop during synchronous ingest. No systemd/production changes made.

## Changed files (exact)
- `src/ref_cli/transcript_block.py` — probe lease + ProbeDecision + epoch-aware finish + hardened parsing (corrected from reviewed version).
- `src/ref_cli/cli.py` — `_fetch_youtube_transcript_provider` extraction; `begin_probe`/`_finish_youtube_probe` scope; pre-legacy cooldown recheck; removed unconditional `clear_block`-on-success (now ownership/epoch-aware via `finish_probe`).
- `tests/test_transcript_probe_concurrency.py` (new, 19 tests) — threaded + real OS multi-process single flight, stale-success protection, epoch precedence, crash/lease bounds, backoff+recovery, 11 malformed-marker cases + implausible timestamp.
- `tests/test_transcript_block.py` — updated to corrected API (23 tests remain green).
- `README.md` — corrected cooldown/probe wording (cross-process tested; no disconnect fix claim).
- `.codex/notes/agent-handoff.md` (this file) and `.codex/notes/current-task.md` — status/claims correction.
- `.github/workflows/tests.yml`, `pyproject.toml` — unchanged from prior implementation (CI gate + `httpx` fix).

## Verification (exact commands/results, Python 3.12.3, dedicated worktree)
- **Fail-at-reviewed-SHA demonstration:** with `src` reverted to the reviewed implementation (reviewed head = `0c232634f84c80861cd1a7012244245af41bf8d5`, app code identical to `d2b2a02`):
  - `test_threaded_recovery_probe_is_single_flight` → **FAILED** (both threads contacted provider)
  - `test_multi_process_recovery_probe_is_single_flight` → **FAILED** (`got 2` provider calls across two OS processes)
  New-API probe tests did not exist at the reviewed SHA.
- After correction (same tests): both **PASS** (exactly 1 provider call).
- Focused: `python -m pytest -q tests/test_transcript_block.py tests/test_transcript_probe_concurrency.py tests/test_transcript_blocking.py tests/test_api.py tests/test_youtube_api_notes.py tests/test_api_client.py` → **118 passed**.
- Full: `python -m pytest -q` → **326 passed** (307 prior + 19 new).
- `python -m compileall -q src get_transcript.py` → OK. `git diff --check` clean.
- No Aether/uv/ruff/mypy gates exist for this repo (not claimed).

## Final SHA / CI
- Implementation head (code+tests+docs-README) and final branch SHA are reported in `[REVIEW-REQUEST]`; both GitHub Actions workflows (push + PR) must be verified green on the exact final pushed SHA — see REVIEW-REQUEST for run links.

## Known issues / risks
- Cross-process single-flight uses an atomic marker + file lock; no distributed lease beyond the bounded window (documented; sufficient and within scope).
- Marker persistence failure degrades cooldown/lease to process-local for the affected process only.
- Live production validation (stop-in-flight disconnect + real ban recovery on minion) is OPEN and explicitly not claimed here; requires operator authorization.
- API remains unauthenticated (trusted network only); SSRF DNS/redirect hardening deferred.

## Deferred work
- Async/durable ingest architecture, full SSRF hardening, proxy/VPN rotation, deeper packaging/linters, deployment and merge to `main` (require user authorization).

## Exactly one recommended next step
Architect: independently re-review corrected draft PR #16 (probe-ownership lease, epoch-aware clearing, hardened parsing, threaded AND real multi-process regression evidence, corrected disconnect claims); if accepted, then (separately, user-authorized) drive the production cutover and the live stop-in-flight validation.

## Local/working-tree notes
- Dedicated worktree `/tmp/opencode/ref-issue-15`; production checkout at `/home/draeician/git/personal/ref` untouched (its modified `TODO.md` and untracked `BAD`, `advisors.md` remain intact).
- WIP markers: `/tmp/opencode/wip-marker-issue-15.txt`, `/tmp/opencode/wip-marker-issue-15-v2.txt`; no ephemeral files committed.
