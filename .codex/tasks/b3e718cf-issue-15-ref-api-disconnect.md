# [fix] Issue #15: ref-api disconnect during YouTube IP-block capture

- Task ID: b3e718cf
- State: QUEUED FOR IMPLEMENTATION (not complete)
- Priority: High — API ingestion reliability
- GitHub issue: https://github.com/draeician/ref/issues/15
- Work branch: `fix/issue-15-ref-api-disconnect`
- Immutable starting main commit: `276ea2afdfd8ea401f1849ba50b847225487f9ee`
- Role: OpenCode coding agent (implementer); ChatGPT (architect/reviewer).
- Authoritative project context: `README.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, and this task.
- Canonical pointer: `.codex/notes/current-task.md`; handoff: `.codex/notes/agent-handoff.md`.

## Incident evidence (do not reinterpret as a proven root cause)

On `minion`, `GET http://127.0.0.1:8000/health` succeeded with version `1.6.12b1.dev40+g276ea2afd.d20261010` (matching main). A `ref -d 3` ingest of `https://www.youtube.com/watch?v=c6u87wtQzTw` failed with `requests.exceptions.ConnectionError` wrapping `RemoteDisconnected('Remote end closed connection without response')`. Issue #15 has repeated `YouTube blocked transcript requests` warnings for six *different* video IDs. A healthy GET and disconnected POST are distinct observations; blocked transcripts may be related but have not been demonstrated to cause the disconnect. `ref --api-status` is not a supported option; `ref --status` is documented.

PR #14 (already merged at the above main commit) added synchronous YouTube description-link discovery during `POST /urls`. `src/ref_api/routes.py` calls `process_many` synchronously; `src/ref_api/service.py` calls `ref_cli.process_url` while holding `_write_lock`, which includes outbound/network work, then processes up to 50 description URLs synchronously; `src/ref_cli/api_client.py` uses a 300-second ingest timeout. `src/ref_cli/cli.py` already catches `RequestBlocked` and sends blocked/unavailable transcripts to `local-transcribe` with `transcript-pending.md` fallback.

No `.github/workflows/` directory or GitHub Actions workflows existed on initial main. Existing `.codex/modes/CODER.md` mentions `src/aether` and `uv`/ruff/mypy/80%-coverage gates from another project; do not assume those commands work in this repository without first checking actual packaging and tools.

## Scope and implementation sequence

1. **Prove failure mode first.** On `minion`, record sanitized and time-bounded `systemctl --user status/show ref-api.service`, `journalctl --user -u ref-api`, worker PID/restarts and resource/OOM evidence around a failed ingest. Verify the Python package and process used by the running service versus the repo. Distinguish connection close caused by process termination, timeout, worker exhaustion, request exceptions, and any unrelated dependency. Avoid printing environment variables, API keys, cookies, or private archive contents.
2. **Reproduce safely.** Add a focused failing deterministic regression test, preferably `TestClient`/isolated temp archive with mocked YouTube metadata, transcript `RequestBlocked` and queue behavior. Use isolated/staging service tests for HTTP disconnect behavior if necessary. Do not repeatedly submit live YouTube URLs to the production archive to debug.
3. **Implement the smallest supported repair and the explicitly required IP-block cooldown.** The HTTP disconnect is a separate investigation: prove or constrain its cause; fix it if evidence supports an isolated correction and ensure requests return bounded, truthful per-URL results rather than dropping the TCP connection. Independently implement the YouTube transcript cooldown specified below (user-confirmed architectural decision), even if the HTTP disconnect cause remains unknown. Preserve existing queue-first architecture and pending-file fallback; no new scheduler/worker, proxy dependency, or parallel queue. Do not implement unrelated speculative changes.

### Required architect decision: IP-block cooldown (user-confirmed, 2026-10-13)

- Treat `RequestBlocked`/`IpBlocked` (or the library's already-recognized equivalent) as a *host public-IP transcript fetch* block, not a video-specific absence of captions. Do not set cooldown for unrelated failures such as disabled transcripts, network timeouts, metadata errors or generic HTTP 429 unless explicitly verified to be the same IP block.
- On the **first confirmed blocked transcript request**, set a single global *YouTube transcript retrieval* cooldown for this archive host, **60 minutes by default**, with a configurable duration (e.g. `REF_YOUTUBE_TRANSCRIPT_BLOCK_COOLDOWN_SECONDS`, default `3600`; document the chosen interface). The duration is an implementation default, not a request to wait for user input.
- Persist a small, nonsecret expiry marker in the configured archive/transcripts state area, outside the Git repository, so the protection survives process restart and applies to separate CLI/API processes sharing the archive. Protect concurrent read/modify/write safely; atomic updates and a short critical section only for state are desirable. Do **not** reuse the reference write lock for slow remote network calls or create a scheduler/control plane. A storage failure must not break capture; use a safe in-process fallback and document the limitation.
- Before any provider **transcript** fetch path (enhanced and legacy), check the marker. During cooldown, do not call `youtube-transcript-api` at all; do not fall through from enhanced to legacy; do not generate a per-video IP-ban WARNING. If transcript JSON is already present locally, keep it and do not enqueue. Otherwise use the existing `local-transcribe` queue-first path and fall back to `transcript-pending.md` exactly as today, honoring duplicate/active/completed/requires_force outcomes. Still retrieve metadata and show notes as before; their APIs are not assumed blocked.
- On expiry, allow the next eligible attempt as a controlled probe. On success, clear/reset the blocked state; on another confirmed IP block, extend expiry by a fresh cooldown period. Concurrent requests should not stampede into multiple remote probes immediately after expiry. Do not extend expiry merely by processing videos while already blocked. Never retry provider requests in a rapid loop.
- Log one concise WARNING on transition into blocked state, including expiry/duration (without secrets); skipped attempts during cooldown can be DEBUG/INFO or recorded in normal structured queue outcome, without repeated block WARNINGS.
- Deterministic mocked tests must verify first block, subsequent videos skipping remote calls, expiry/re-probe, concurrent suppression, persistence across fresh processes/instances, no false trigger on unrelated failures, existing transcript reuse, queued and duplicate queue outcomes, and graceful pending-file fallback. Exercise local CLI and API ingest paths where applicable. Document cooldown configuration and operational reset/override safety.
4. **Protect existing contracts.** Keep `POST /urls` request/response schema, API status labels, the 50-link show-note cap, nonrecursive discovery, normal CLI mode, skip/security rules, idempotent archive writes, and local-transcribe `enqueued`/`existing_active`/`requires_force`/fallback semantics. No credentials in logs. Avoid holding a process-wide archive write lock across network/queue operations **only if** the write path can be safely separated without duplicate/corrupted entries; otherwise document as deferred architecture debt, not a casual unlock.
5. **Add a minimal remote CI gate.** No GitHub Actions workflow exists: add `.github/workflows/tests.yml` to run the repository's actual pytest suite on pushes to `fix/issue-15-ref-api-disconnect` and on pull requests, using a supported Python version (prefer 3.12). Ensure test dependencies actually install. Do not introduce Aether-specific src paths or falsely claim unconfigured lint/mypy gates. If an existing workflow appears after task start, reuse it and document the change rather than creating a duplicate.
6. **Document/operator instructions.** Update `README.md` only where needed for behavior/recovery diagnosis; correct unsupported flag references if touched. Record the sanitized root-cause evidence and effective verification in the handoff. Do not modify or restart the production service, change the production archive, alter systemd units, or deploy from this branch without explicit authorization.

## Likely code/test review areas (modify only those proved necessary)

- `src/ref_api/service.py`, `src/ref_api/routes.py`, `src/ref_api/server.py`
- `src/ref_cli/cli.py`, `src/ref_cli/api_client.py`, `get_transcript.py`
- `src/ref_cli/youtube_extract.py`
- `tests/test_api.py`, `tests/test_youtube_api_notes.py`, `tests/test_transcript_blocking.py`, `tests/test_api_client.py`
- `README.md`, `.github/workflows/tests.yml`, `.codex/notes/agent-handoff.md`

## Acceptance gates (all required)

- A. Handoff identifies *observed* disconnect mechanism with timestamps, HTTP behavior, process/service state, and no unproven assumption that IP blocking alone caused it. If truly unreproducible, explicitly state which checks were performed and what is still unknown; do not claim incident resolved.
- B. Automated regression tests fail on pre-fix behavior and pass after the fix. Explicitly verify persisted 60-minute configurable blocked-IP cooldown, suppressed remote transcript calls/warnings, queue-first/fallback semantics, concurrency and expiry/probe behavior, then `POST /urls` valid API response and `GET /health` remaining available. Cover batch behavior, queue deduplication, show-note discovery and error isolation where affected.
- C. The measured failure is repaired in an isolated/staging integration test. If live proof is unavailable without production modifications, report this as an open production validation gate.
- D. Run focused tests and `python3 -m pytest -q` (full suite), `python3 -m compileall -q src get_transcript.py`; report actual counts and environment. If other reproducible quality tools exist, run their configured commands; avoid claiming inherited Aether gates.
- E. Create a **draft PR** targeting `main`, with `Fixes #15`, this task path, summary, root cause, testing, deployment/rollback and residual risks. Do not merge. Push only the development branch.
- F. Required GitHub Actions run(s) must finish green on the **exact final pushed head SHA**, not an earlier intermediate commit. If red, examine failing jobs, repair, push a new SHA and reverify. If CI cannot run, mark gate blocked instead of claiming success.
- G. Update `.codex/notes/agent-handoff.md`: current state, work completed, concrete changed areas, decisions, evidence, verification (commands/results and remote SHA/CI), risks, deferred work, **exactly one recommended next step**. Check no WIP/local artifacts are committed. Preserve all unrelated local changes.

## Deferred/out of scope

- Replacing synchronous ingest with a durable asynchronous job system and changing the API contract.
- Comprehensive SSRF DNS/redirect protection (known existing concern; do not weaken current guards).
- Blanket proxy/VPN rotation to evade YouTube bans.
- Production deployment or merge to `main`.
- General packaging/linters/refactors outside the incident and its minimal CI gate.

## Implementation agent workflow

Create an external/local WIP marker **before repository actions**; inspect local status and preserve user's uncommitted `TODO.md`/`gitc` or any other files. Prefer a dedicated worktree; do not switch or reset a dirty production checkout. Fetch and work from `origin/fix/issue-15-ref-api-disconnect` (already created). Read all authoritative docs, implement with tests, update handoff, commit using `[fix]`/`[test]`/`[ci]`/`[docs]` conventions, push only task branch, create draft PR, and verify remote CI. Post `[REVIEW-REQUEST]` with exact head SHA. Never merge or deploy. 
