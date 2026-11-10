# [ops] NFSv3 producer cutover readiness preflight

- **Task ID:** `19294572`
- **Owner:** OpenCode
- **State:** REVIEW
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/review/` (preflight complete; cutover not executed).
- **Branch:** `ops/nfs-v3-producer-preflight`
- **Base:** `origin/main` = `2cf3e9c755004be5a1072e7f38c6cfe613efe0e2`
- **Related deployment task:** `7d2c9e41` (remains in `.codex/tasks/review/`, State `REVIEW`; ownership unchanged)
- **Deliverable:** `docs/investigations/nfs-v3-cutover-readiness.md`
- **Authorization:** Live **read-only** verification and a documented cutover plan.
  No mount/remount, service restart, queue or archive write, production config
  edit, canary, or main merge.

## Claim

```
[CLAIM] 19294572 NFSv3 producer cutover readiness preflight
repo: draeician/ref@ops/nfs-v3-producer-preflight
actor: OpenCode  role: Deployer/preflight
task-file: .codex/tasks/wip/19294572-nfs-v3-producer-cutover-preflight.md
plan:
- Phase 1: read-only worker liveness on aether (PID, NFSv3, NLM, heartbeat, logs,
  processing/.tmp, single-worker evidence)
- Phase 2: read-only minion-26 producer preflight (health/version, lt provenance,
  queue UUID/hash, mount health, v3 export, sudo/mounts, capacity/inodes,
  /mnt/ref-queue-v3, UID/ACL, consumers, ref-api env)
- Phase 3: exact cutover/rollback design
- Phase 4: single-canary plan (not executed)
- Phase 5: report + HANDOFF + docs-only PR; keep 7d2c9e41 in REVIEW
```

## Acceptance checks

1. Worker liveness either demonstrated with fresh evidence, or a documented
   STOP with a separate recovery proposal.
2. All Phase 2 checks recorded with exact commands and observed outputs.
3. Cutover design names the escaped mount unit, validation, persistence,
   `ref-api` ordering, queue env/config, and unchanged UUID/NFS guard.
4. Fresh-backup and ordered rollback procedures are complete; stale 2026-11-09
   backup explicitly rejected.
5. Canary plan defines unique URL checks, before/after counts, expected
   transitions, worker claim, JSON/reconciliation validation, and STOP triggers.
6. Report and HANDOFF updated; `7d2c9e41` untouched and still in `review/`.
7. `git diff --check`, secret scan, and Markdown fence checks pass; exact-head CI
   green; PR opened; no merge.

## Result

- Report: `docs/investigations/nfs-v3-cutover-readiness.md`.
- **Worker liveness: PASS** — PID `1011088` matched lock/state; heartbeat
  advanced; one worker/NLM owner; no stuck reservation; stale `.tmp` harmless.
  Stability caveat: GPU core-dump at 14:29 (`NRestarts=14`) and empty-transcript
  failures.
- **Mount installation: GO, conditional** — NFSv3 export available, path free,
  sudo required, fresh backups and post-mount ACL validation mandatory.
- **Canary: NO-GO now** — 1,373 same-priority pending jobs, recent worker
  instability, and unverified v3 ACL. Conditional GO after separate authorization
  for backlog/priority, a stability window, ACL validation, and fresh liveness
  checks.
- Queue backlog (`1,373` pending, `origin=ref`, `priority=20`) and the recreated
  529-line `transcript-pending.md` were observed and left untouched.
- `7d2c9e41` untouched and still in `review/` with State `REVIEW`.
- No mount, remount, service restart, queue/archive write, config edit, canary,
  backlog replay, or main merge was performed.

## Review correction — rollback/service/gate (2026-11-10)

- Report §4.11 and §5.7 now capture the exact original `ref-api.service` unit,
  effective `FragmentPath`/`DropInPaths`/`ExecStart`/`EnvironmentFiles`, and the
  fact that no drop-ins currently exist.
- §7 rollback now restores the service unit/drop-ins, removes the v3 gate and
  dependency, reloads both `--user` and system managers, verifies the effective
  unit, then restarts and validates against the original `/opt/md2` queue.
- §5.4 now defines a fail-closed `ref-queue-v3-gate` that validates target,
  source, NFS protocol/options, UUID/hash, and permissions before API start.
- Canary NO-GO is unchanged; no authorization is implied.
