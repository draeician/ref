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
3. **Implement the smallest supported repair.** Fix the identified disconnect cause and ensure blocked transcripts do not abort parent reference recording or show-note discovery. Ensure requests return bounded, truthful per-URL results rather than dropping the TCP connection. Preserve existing queue-first architecture and pending-file fallback. If the evidence demonstrates a blocked-IP request storm, add a small concurrency-safe, time-bounded suppression/circuit-breaker for YouTube transcript requests (no repeated provider calls while blocked), with deterministic expiry and tests; do not add a scheduler/worker, proxy dependency, or persistent parallel queue. Do not implement speculative changes unrelated to the measured failure.
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
- B. Automated regression test fails on pre-fix behavior and passes after the fix. Verify a blocked YouTube transcript is recorded/queued or correctly falls back, then `POST /urls` returns a valid API response and `GET /health` remains available. Cover batch behavior, queue deduplication, show-note discovery and error isolation where affected.
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
