# Agent handoff — ref-cli

## Current state
- **QUEUED / NOT IMPLEMENTED.** Architect created issue-specific branch and canonical task records, no application code modified.
- Repository: https://github.com/draeician/ref
- Default/protected branch: `main`; starting SHA `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- Development branch: `fix/issue-15-ref-api-disconnect`.
- Task: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`.
- Pointer: `.codex/notes/current-task.md`.
- GitHub issue: https://github.com/draeician/ref/issues/15
- Previous work: PR #14 merged at starting main SHA, enabled synchronous YouTube show-note discovery.

## Completed this handoff cycle
- Inspected remote repo branch state, historical PRs, source path, tests, README, local-transcribe contract and existing `.codex` agent guidelines.
- Captured user-provided production evidence: `GET /health` succeeded on minion with version `1.6.12b1.dev40+g276ea2afd.d20261010`; `ref -d 3` request produced HTTP connection closed without response; `ref --api-status` is not supported (`ref --status` is).
- Open issue #15 reports six different blocked YouTube transcript IDs in a short span. **Cause of HTTP disconnect not confirmed.**
- Inspected routes and service: HTTP ingest and show-note fanout synchronous, write lock surrounds CLI processing and external operations. Existing blocked-transcript path queues in local-transcribe, falling back to transcript-pending file.
- Inspected CI: no `.github/workflows` directory or configured GitHub Actions on initial `main`. Existing `.codex/modes/CODER.md` contains stale Aether/uv lint/coverage instructions, not automatically valid for ref.
- No tests run, no live server commands executed by architect, no production changes or deploy.
- Subsequent architect update: user explicitly confirmed desired IP-block cooldown behavior; committed it to the canonical task on the same development branch. This is a scoped requirement, not a verified implementation.

## Changed areas
Only task/planning documents on the development branch: `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`, `.codex/notes/current-task.md`, and this handoff file.

## Important decisions / invariants
- **2026-10-13 user-confirmed decision:** independently add a persisted, cross-process, configurable 60-minute-default YouTube transcript IP-block cooldown. On the first confirmed `RequestBlocked`/`IpBlocked`, suppress additional remote transcript calls and repetitive warnings, while preserving existing transcripts or queueing missing ones via local-transcribe with the pending-file fallback. One probe after expiry; reset on success or renew on confirmed block. Tests cover concurrency, persistence, expiry, local and API calls, deduplication and failure fallback. Full detail is now mandatory in `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md`.
- Diagnose the server HTTP disconnect independently; do not assert the transcript IP ban caused `RemoteDisconnected` without evidence.
- Preserve current `POST /urls` schema, 50-link cap, nonrecursive discovery, queue-first local-transcribe API, pending-file fallback, archive safety and existing security guardrails.
- No separate scheduler/queue, proxy bypass or speculative bulk refactor.
- Implementation in branch and draft PR only; main merge and deployment require user authorization.
- Introduce minimal pytest CI workflow because there was no existing remote CI. Verify success on final pushed SHA.

## Verification performed
- Remote GitHub code/issue/PR, branch metadata, files and CI configuration inspected. No actual patch, tests, isolated HTTP reproduction, or production debugging has yet been performed.
- Prior PR #14 described 284 passing tests, but **this is historical evidence only**, not validation of issue #15.

## Known issues / risks
- Exact cause of HTTP RemoteDisconnected unknown; blocked transcripts may be coincident. IP-block cooldown is a separate confirmed requirement, not proof of API root cause.
- Existing synchronous batching, nested show-note processing, and global archive lock are latency risks.
- API is unauthenticated; use trusted network only.
- SSRF hardening for DNS/redirect targets is deferred existing debt.
- Live production file/service state inaccessible here; local `TODO.md` and untracked `gitc` were reported in earlier conversation. Agent must independently inspect and avoid clobbering work.

## Deferred work
- Async job architecture, full SSRF hardening, proxy strategy, broader packaging or linters, deployment and default-branch merge.

## Exactly one recommended next step
OpenCode should claim and implement `.codex/tasks/b3e718cf-issue-15-ref-api-disconnect.md` on `fix/issue-15-ref-api-disconnect`, supply root-cause evidence, update this handoff, push and open a draft PR, and verify required exact-SHA CI before requesting independent review.
