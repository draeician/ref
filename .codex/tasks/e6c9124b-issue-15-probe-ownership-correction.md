# [fix] Issue #15 QA correction: transcript probe ownership and honest disconnect status

- Task ID: e6c9124b
- State: CORRECTIVE TASK / BLOCKING PR #16 MERGE
- Priority: High
- Original issue: https://github.com/draeician/ref/issues/15
- Draft PR: https://github.com/draeician/ref/pull/16
- Branch: `fix/issue-15-ref-api-disconnect`
- Reviewed implementation SHA: `d2b2a028253cbc09dd2dc94b28696ee139b3eafb`
- Original task/spec: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`
- Canonical recovery: `.codex/AGENTS.md`, `.codex/modes/CODER.md`, `.codex/notes/current-task.md`, `.codex/notes/agent-handoff.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`.

## Independent QA verdict

**FAIL** despite green push and PR CI (each ran 307 passing tests on reviewed SHA). Actual code review found two linked races and a misstatement of HTTP repair. Do not merge or deploy; do not advance roadmap.

1. `src/ref_cli/cli.py:254-273` enters `probe_guard` solely to read `is_blocked`, exits the guard **before** either enhanced or legacy remote provider call (from line 2005 onward). `src/ref_cli/transcript_block.py:301-315` has a process-local thread lock only. After cooldown expiry two CLI processes (or two threads) can concurrently pass the check and issue provider transcript calls, violating original requirement "one controlled probe". The test `test_concurrent_enter_block_does_not_extend` only checks simultaneous marker writes, not simultaneous provider fetches. New CI is blind to this race.
2. `cli.py:2026,2183` calls `transcript_block.clear_block` **unconditionally** on a successful transcript. An older in-flight success can erase a *newer* cooldown entered by another process after a blocked request. This reopens the ban storm. Existing tests only cover one sequential success/probe.
3. `PR #16` title/body/handoff imply "ref-api disconnect hardening" makes POST bounded/avoids RemoteDisconnected. Actual observed mechanism per agent is an operator-initiated systemd stop while a synchronous request is in flight, followed by SIGKILL after ~90 seconds; no service/shutdown code changed, and a future stop can still interrupt the HTTP connection. The transcript cooldown reduces provider load but does not guarantee bounded synchronous show-note fanout nor fix SIGKILL. The live production gate remains open and must stay clearly marked as such. Do not introduce an async framework solely to close this review.
4. Defensive follow-up in the same small cooldown module: `_read_marker_unlocked` validates `blocked_until` but performs unguarded `float(set_at)`/`int(duration_seconds)`. A valid JSON file with malformed metadata can raise, failing ingest rather than safely ignoring a corrupt nonsecret marker. Add a regression and fail-safe parse.

## Scoped corrective implementation

- Implement an atomic, **cross-process** single-flight *recovery probe lease* using the existing cooldown marker/short `fcntl` state lock (not a scheduler or separate queue). On expiry, exactly one CLI/API caller claims a bounded ownership token/lease under the file lock; others skip remote transcript calls and follow the current queue-first or pending-file fallback. The lease must expire after a bounded period so process crashes cannot wedge ingestion. Release or transition on success, confirmed block, unrelated fetch failures, and exceptions; never keep the file lock open across network calls. Do not serialize otherwise-healthy routine transcript downloads unnecessarily. A failed marker persistence/lease claim must degrade safely to process-local protection, not fail capture.
- Make cooldown-clearing **ownership/version-aware**: only the current recovery probe may clear the cooldown; ordinary in-flight pre-block successes may not erase a newer marker or newer lease. If a block is detected while an earlier request is running, the blocker takes precedence. Prevent a stale probe from clearing a renewed block. Keep transition warnings once per block epoch.
- For an enhanced non-block error followed by legacy fallback, recheck active cooldown before contacting the legacy provider, so another process's newly discovered block cannot be bypassed.
- Harden marker parsing against malformed numeric metadata, `NaN`, infinities, unreasonable timestamps and unexpected types without throwing into API capture. Respect existing controlled defaults and avoid leaking private state.
- Preserve 60-minute default, env/config precedence, disk transcript reuse, `local-transcribe` queue results and `transcript-pending.md` fallback, show-note metadata and 50-link cap, HTTP API response schema, and current security constraints. No new scheduler, proxy rotation, production restart or direct main push.

## Required deterministic regression tests

- Two threads enter an **expired** cooldown together: precisely one provider call, other video skipped and routed to queue/fallback. Use barriers/events to hold first provider fetch in flight while testing second.
- Two independent OS processes using the same transcripts directory after an expired marker: precisely one claimed recovery probe while another skips; no over-claim that a thread test simulates multi-process ownership.
- Pre-ban provider fetch A succeeds *after* B records a fresh block: A cannot clear B's marker (test final `is_blocked` and provider call count).
- Probe result stale after another blocked renewal: stale probe cannot remove/overwrite the current epoch.
- Probe fails for an unrelated non-block reason or owner crashes: the lease is bounded; no permanent outage. Verify eventual recovery without a stampede.
- Malformed marker JSON/numeric fields must not throw and must not poison queue capture.
- Existing queue duplicate/active outcomes, one warning per transition, no remote calls during active cooldown, restart persistence, API `POST /urls`/health, and old suite remain green.

## Root-cause and PR-language correction

- Revise PR #16 description and handoff to **separate** (a) tested transcript cooldown hardening from (b) systemd graceful-stop/SIGKILL observation. Clearly state the HTTP socket still can drop on a service stop during synchronous ingest, and that production validation needs future explicit operator authorization. Remove any blanket promise of bounded `POST /urls` responses. No systemd/production changes under this task.
- Update README statements like "one probe after expiry" only when actually supported by tested cross-process behavior. Correct `.codex/notes/current-task.md` and handoff so neither claims task is queued for initial implementation nor accepted until review.
- Preserve a compact, sanitized evidence summary with timestamps and observed versus inferred facts; avoid claiming architect independently accessed minion journal (architect only reviewed the submitted handoff).
- Commit/update original draft PR #16 on the **same** development branch; do not open competing PR or merge.
  
## Acceptance gates

1. New concurrency tests demonstrate failures at reviewed SHA and pass after fixes. Meaningful real OS process exercise is required for the cross-process claim.
2. Focused tests and full `python3 -m pytest -q` and `python3 -m compileall -q src get_transcript.py` pass; include exact counts. Respect configured compatibility; no unrelated refactor.
3. Verify push and PR GitHub Actions **complete successfully on the exact new final SHA**; inspect/redrive failed jobs as necessary.
4. Update canonical `.codex/notes/agent-handoff.md` with root-cause distinction, changed areas, version/lease design, tests, risks, exact remote SHA/CI, and exactly **one** recommended next step.
5. Preserve user local checkout/WIP, no ephemeral files in commit, draft PR only, never main push, no production restart/deployment. Post `[REVIEW-REQUEST]` on PR with evidence.
6. Do not claim the live deployment/stop-in-flight gate has passed; this review closes only after independent QA of corrected SHA. The unresolved production validation is a separate cutover gate.

## Exactly one next action

OpenCode: pull the latest existing issue branch safely, implement this narrow correction on PR #16, update canonical handoff, and return the new exact remote SHA with both green workflow links.
