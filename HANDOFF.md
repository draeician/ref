# HANDOFF — 7d2c9e41 production deployment (ref + queue producer)

**Date:** 2026-11-09/10 (UTC)
**Task ID:** `7d2c9e41`
**Owner:** OpenCode
**State:** REVIEW (deployment documentation merged; task not DONE)
**Branch:** `ops/deploy-remote-api-queue-fix` (merged and deleted)
**Authorized ref:** `ce73299760787abfd4e69b29c51c450cae0ab9d0`
**Authorized local_transcribe:** `b3cf22ee5da337fab9dcd37fb97506f5beab012b`
**Task record:** `.codex/tasks/review/7d2c9e41-deploy-remote-api-queue-fix.md`

## Stabilization closure — final architecture decision (2026-11-10)

- **Housekeeping task:** `.codex/tasks/done/8bc15624-close-stabilization-round.md`
  (State **DONE**; documentation and task lifecycle only).
- **Decision:** the proposed additional NFSv3 producer mount for `minion-26` is
  **cancelled, superseded, and not authorized**.
- **Retained:** the existing NFSv4.2 producer mount on `minion-26` and the
  existing NFSv3/NLM worker mount on `aether`. Do not install
  `/mnt/ref-queue-v3`.
- **Preserved:** the shared queue path and UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582`; do not weaken NFS/NLM safety
  validation.
- **Not proven:** cross-protocol producer safety. A separate **read-only** audit
  is required before any future proposal; this closure does not claim it has been
  demonstrated.
- **Historical evidence preserved:** both NFS investigation documents retain
  their observations, commands, and proposed procedures, now marked superseded
  at the top.
- **No production action:** no mount, configuration edit, service restart,
  queue/archive write, canary, or backlog replay was performed by this closure.

### Final closure record (2026-11-10/11)

- PR [#41](https://github.com/draeician/ref/pull/41) was reviewed, approved, and
  merged with a **normal merge commit** (no squash, rebase, force-push, or direct
  push to `main`): `bcf864e775626004215236e8f93341feb453df73`, parents
  `b9bbffac64ff84f4c25ecd5053c03eb6d25d4d96` and
  `d663ac13ed3725320a53dbd8bb79190f980539a4`.
- Approved PR head: `d663ac13ed3725320a53dbd8bb79190f980539a4` (matched at
  merge). Pre-merge exact-head CI: run `42925244767` (`tests`,
  `pull_request`), **success**.
- Post-merge `main` CI: run `42928999802` (`tests`, `push`) on `bcf864e`,
  **success**. The approved head is an ancestor of `origin/main`.
- The merged housekeeping branch was deleted locally and remotely; confirmed
  absent with `git ls-remote --heads origin`. Only `main` and the two preserved
  branches remain.
- The closure record is delivered in a separate docs-only PR that **remains open
  for ChatGPT review and is not merged**.

### Branch audit (2026-11-10)

| Branch | Classification | Action |
| --- | --- | --- |
| `main` | Canonical; `b9bbffa` equals `origin/main` | Keep |
| `docs/unified-ref-consolidation-plan` | Open draft PR #29; 3 commits ahead / 44 behind; not merged | Preserve |
| `fix/youtube-auto-show-notes-api` | Unmerged divergent work; 6 commits ahead / 144 behind; no PR; all six commits absent from `main` | Preserve pending separate review |

At audit time, no merged housekeeping branch was eligible for deletion. After PR
#41 merged, only its own branch was deleted. Neither preserved branch is
authorization to merge or delete it.

### Remaining work (follow-ups only, not authorization)

1. Run a separate **read-only** audit of cross-protocol producer safety; do not
   claim it has been proven.
2. Investigate the origin of the 1,373 pending `origin=ref`, `priority=20` jobs.
3. Investigate the recreated 529-line `transcript-pending.md`; do not replay or
   delete it.
4. Track worker GPU crashes/core-dumps and empty-transcript failures.
5. Complete the outstanding remote-client deployment, including nomnom access.
6. Design a safe historical transcript recovery path; no bulk replay.
7. Review existing unrelated GitHub issues (#17, #12, #4, #3) and draft PR #29
   separately.

## NFSv3 producer cutover readiness preflight (task 19294572 — historical)

- **Report:** `docs/investigations/nfs-v3-cutover-readiness.md` (historical;
  proposed mount superseded and not authorized).
- **Task:** `.codex/tasks/done/19294572-nfs-v3-producer-cutover-preflight.md`
  (State **DONE**: preflight complete; no cutover executed, and the proposed
  mount is superseded).
- **Worker liveness (aether): PASS.** Fresh PID `1011088` matches
  `worker.lock`/`state.json`; one service, one process, one NLM lock; heartbeat
  advanced `16:24:07 → 16:32:53` and the claimed execution changed
  `104072e0… → fe513590…`; completed advanced 5710 → 5711. Heartbeat is
  claim-driven, so the old 2026-11-07 value is explained by an idle/old worker,
  not a stuck one. The Oct-15 zero-byte `.tmp` is a harmless orphan (its
  execution completed 2026-10-19); do not delete it.
- **Worker stability caveat:** a GPU illegal-memory-access core-dump at
  `2026-11-10 14:29:45` caused a systemd restart (`NRestarts=14`); the worker
  recovered the in-flight job. Repeated `'transcript' is empty` failures were
  also observed. Live, but not proven stable.
- **Producer preflight (minion-26):** `/health` ok at
  `1.6.12b1.dev157+gce7329976`; `ref-api` active with `NRestarts=0`; `lt` 0.8.1
  from pipx git commit `b3cf22e`; queue UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582` and `queue.id` hash `28998c9e…`; NFSv4.2
  `/opt/md2` healthy; server NFSv3 export available to `192.168.22.0/24`;
  `/mnt/ref-queue-v3` absent/free; 1.1T free / 2% inodes; passwordless sudo
  unavailable; queue ACL is NFSv4 (`+`) and v3 ACL mapping is unverified.
- **Queue state (OBSERVED, unexplained):** `1,373` pending, all `origin=ref`,
  `priority=20`; completed 5711, failed 206, cancelled 670, keys 9770;
  `transcript-pending.md` is present again (529 lines, sha256
  `a7c3c5e3…`). This appeared after the 2026-11-09 baseline (`pending=0`) and
  was not created by this preflight. Do not replay or delete it here.
- **Recommendation:** **GO** for authorized mount installation and post-mount
  validation; **NO-GO for the canary now** because a ref-produced canary
  (`priority=20`) sorts behind 1,373 same-priority jobs, the worker has recent
  GPU core-dumps/empty-transcript failures, and v3 ACL access is unverified.
  Canary becomes **conditional GO** after a backlog/priority authorization, a
  stability window, v3 ACL write validation, and fresh liveness checks.
- **Rollback / service restoration:** take fresh backups immediately before any
  change; never use the 2026-11-09 `local-transcribe.config.yaml.before` (stale
  `/tmp/lt-smoke-queue-59553` / `6a058908-116f-41c9-987f-d5f4ef38667e`).
  Capture the exact original `ref-api.service` unit, its effective
  `FragmentPath`/`DropInPaths`/`ExecStart`, and the (currently none) drop-ins.
  Rollback restores that unit so the only `ExecStartPre` is
  `/usr/bin/mountpoint -q /opt/md2`, restores the original queue paths, removes
  only the cutover-owned gate/`10-ref-queue-v3.conf` and dedicated mount, reloads
  **both** managers (`systemctl --user daemon-reload` and
  `sudo systemctl daemon-reload`), verifies the effective unit with
  `systemctl --user cat`/`show`, then restarts and validates against the original
  `/opt/md2` queue. It never recursively deletes the drop-in directory or
  overwrites unrelated drop-ins. Ordered procedure is report §7.
- **Fail-closed startup gate:** the proposed cutover adds
  `~/.local/bin/ref-queue-v3-gate` as an `ExecStartPre` after the existing
  `/opt/md2` check. It parses the comma-delimited mount options into exact
  tokens and requires exactly one `vers=3`, `mountvers=3`, `proto=tcp`, `hard`,
  and `local_lock=none`; `mountvers=3` cannot satisfy `vers=3` and
  `mountproto=tcp` cannot satisfy `proto=tcp`. It rejects wrong or duplicate
  values, `soft`, `nolock`, and local-only locking (`local_lock=all|flock|posix`).
  It also validates the exact target, `nfs` fstype, source
  `depot.draeician.com:/mnt/tank/md2`, `queue.id` hash `28998c9e…`, UUID
  `8c6fc098…`, and producer read/search/write access. Missing or mismatched
  values prevent the API from starting; §5.4 documents negative tests for each
  wrong protocol/option combination. After editing the user unit, the cutover
  must run `systemctl --user daemon-reload` and verify the effective two
  `ExecStartPre` lines with `systemctl --user cat`/`show` before restarting.
  This gate supersedes the earlier mountpoint-only suggestion in the merged
  investigation.
- **Canary NO-GO preserved:** this correction does **not** authorize a canary;
  the 1,373-job backlog, GPU instability, and unverified NFSv3 permissions remain
  unresolved.
- **Unchanged:** `queue.expected_uuid` and `expected_nfs_version: 3`;
  `/opt/md2` and the aether worker mount are not modified.
- **Deployment task `7d2c9e41` remains in review/ with State REVIEW.**

## NFSv3 cutover preflight documentation merge closure (PR #39)

- Approved head: `792478b530bf5826799025faa49d2aacb5cd53eb`.
- Pre-merge exact-head CI: workflow `tests`, run `42915544619`, **success**.
- PR #39 merged with a **normal merge commit**:
  `df662a65e953e522b5d350183d2090385f8019ab` (parents `2cf3e9c…` and
  `792478b…`). No squash, rebase, force-push, or direct `main` commit.
- Post-merge `main` CI: workflow `tests`, run `42916787616`, head `df662a6…`,
  **success**.
- Final `main` after this merge:
  `df662a65e953e522b5d350183d2090385f8019ab`.
- Documentation-only diff: `HANDOFF.md`,
  `docs/investigations/nfs-v3-cutover-readiness.md`, and
  `.codex/tasks/review/19294572-nfs-v3-producer-cutover-preflight.md` (the task
  was later moved to `done/` by the stabilization closure).
- The PR includes the exact-token fail-closed startup gate, negative
  protocol/option tests, scoped rollback that preserves unrelated drop-ins, and
  the preserved canary **NO-GO**.
- Local and remote `ops/nfs-v3-producer-preflight` deleted after merge; tracking
  refs pruned. Unrelated branches (`docs/unified-ref-consolidation-plan`,
  `fix/youtube-auto-show-notes-api`) preserved.
- At the time of that merge, tasks `19294572` and `7d2c9e41` remained in
  `.codex/tasks/review/` with State **REVIEW**. The stabilization closure later
  completed `19294572`; `7d2c9e41` remains in `review/`. Deployment is not DONE.
  No production mount, config edit, service restart, queue write, canary, or
  backlog replay was performed.
- This closure PR records merge evidence only and changes documentation only.

## NFS investigation documentation merge closure (PR #37)

- Approved head: `02402f3551c947f0a7762fcce776108158b85307`.
- Pre-merge exact-head CI: workflow `tests`, run `42754666584`, **success**.
- PR #37 merged with a **normal merge commit**:
  `5431afbe20b2712d587477f367cab690778a40c0` (parents `6b77a85…` and
  `02402f3…`). No squash, rebase, force-push, or direct `main` commit.
- Post-merge `main` CI: workflow `tests`, run `42842666520`, head `5431afb…`,
  **success**.
- Final `main` after this merge: `5431afbe20b2712d587477f367cab690778a40c0`
  (`6b77a85…` plus the docs-only PR #37, including both approved commits
  `0d0b587…` and `02402f3…`).
- Documentation-only diff: `HANDOFF.md` and
  `docs/investigations/2026-11-10-nfs-producer-mount-investigation.md`.
- Local `docs/nfs-producer-investigation` and its remote tracking ref were
  deleted after merge; refs pruned. Unrelated remote branches
  (`docs/unified-ref-consolidation-plan`, `fix/youtube-auto-show-notes-api`) were
  preserved.
- Task `7d2c9e41` remains in `.codex/tasks/review/` with State **REVIEW**; the
  deployment is not DONE while the blockers below remain.

### Outstanding work preserved after this merge

This merge is documentation/evidence only. The following remain outstanding and
require separate production authorization:

1. Dedicated NFSv3 producer mount not implemented.
2. Worker heartbeat/liveness still unresolved (stale `2026-11-07` heartbeat).
3. Canary not executed.
4. nomnom not upgraded (SSH/pipx deployment outstanding).
5. Historical transcript recovery still outstanding.

## Documentation merge closure (PR #35)

- Approved head: `cc810656ed85905218ef984160c76c0331452901`.
- Pre-merge exact-head CI: workflow `tests`, run `42723569512`, **success**.
- PR #35 merged with a **normal merge commit**:
  `97fa789ab2bf9a51c52c4ce037d5c4c3eedc7861` (parents `ce73299…` and
  `cc81065…`). No squash, rebase, force-push, or direct `main` commit.
- Post-merge `main` CI: workflow `tests`, run `42726678726`, head `97fa789…`,
  **success**.
- Final `main` after this merge: `97fa789ab2bf9a51c52c4ce037d5c4c3eedc7861`
  (`ce73299…` plus the docs-only PR #35).
- Documentation-only diff: `HANDOFF.md` and
  `.codex/tasks/review/7d2c9e41-deploy-remote-api-queue-fix.md`.
- Local and remote `ops/deploy-remote-api-queue-fix` deleted after merge;
  tracking refs pruned. Unrelated branches
  (`docs/unified-ref-consolidation-plan`, `fix/youtube-auto-show-notes-api`)
  preserved.
- Task `7d2c9e41` stays in `.codex/tasks/review/` with State **REVIEW**;
  deployment is not DONE while the blockers below remain.

## NFS producer investigation report

- **Report:** `docs/investigations/2026-11-10-nfs-producer-mount-investigation.md`
- **Findings (OBSERVED):** minion-26 mounts
  `depot.draeician.com:/mnt/tank/md2` over **NFSv4.2** at `/opt/md2`; aether
  mounts the same export over **NFSv3** (with `mountvers=3` and `rpc.statd`) and
  holds the NLM worker lock. Both resolve queue UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582` (`queue.id` sha256 `28998c9e…`).
- **Guard mismatch (OBSERVED):** `queue.expected_nfs_version: 3` is preserved on
  minion-26, so `lt queue path`/`doctor` report `found 4, expected 3`. The
  producer enqueue path does not consult mount validation/NLM; the worker host is
  correctly NFSv3.
- **Recommended next action (PROPOSED, not executed):** add a dedicated NFSv3
  producer mount of the same export, point `REF_LOCAL_TRANSCRIBE_QUEUE_DIR` and
  `queue.path` at it, keep the UUID and NFSv3 guard, then run the bounded canary
  under the report's acceptance criteria.
- **Rollback correction:** the 2026-11-09 pre-deployment backup is **not** a
  valid rollback source — its `local-transcribe.config.yaml.before` predates the
  UUID correction and holds the stale `/tmp/lt-smoke-queue-59553` /
  `6a058908-116f-41c9-987f-d5f4ef38667e`. Take **fresh backups immediately
  before** any future mount/config change; roll back only to that fresh,
  known-good post-correction config (queue UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582`, `expected_nfs_version: 3`). Never
  reintroduce the stale smoke-test values.
- **Mount-unit correction:** do not guess the unit filename. Generate it with
  `systemd-escape --path --suffix=mount /mnt/ref-queue-v3`
  (→ `mnt-ref\x2dqueue\x2dv3.mount`, systemd 259). Validate with
  `systemd-analyze verify` + `daemon-reload` + `systemctl cat`, enable for
  boot persistence, keep the mount independent of `/opt/md2`, and gate
  `ref-api` startup with `ExecStartPre=/usr/bin/mountpoint -q /mnt/ref-queue-v3`.
  The unit remains **illustrative and unauthorized** for installation.
- **Worker-liveness correction:** active systemd status is **not** proof of
  progress, and lock metadata alone is **not** proof of current ownership. The
  stale `2026-11-07T17:50:25+00:00` heartbeat is **unresolved**. Before canary,
  freshly demonstrate: live process/lock match, current logs and
  heartbeat/progress, exactly one worker, and no stuck `processing/` state.
  **If liveness cannot be demonstrated, STOP.**
- **Blockers retained:** dedicated v3 mount untested; guard mismatch unresolved;
  canary not executed; nomnom SSH/pipx deployment outstanding; pending transcript
  recovery not implemented; worker liveness/heartbeat unresolved; `/opt/md2` at
  99%; UID/ACL behavior on a v3 mount unverified.

## Deployed state (minion-26)

- `ref-api.service` runs from the dedicated venv
  `/home/draeician/.local/share/ref-services/ref-api` (Python 3.13.17), now
  installed as `ref-cli 1.6.12b1.dev157+gce7329976` from the authorized
  `ce73299` wheel. `/health` returns that version; `NRestarts=0`, reconciler
  started, no error/traceback lines.
- `ref --status` on minion-26: `Mode: remote`, `Status: ok`, exit 0.
- `lt` is now `local-transcribe 0.8.1` from `b3cf22e`, same Python 3.14.4,
  pipx spec pinned to the commit. No Deno warning.
- Producer config corrected: `queue.path` and `queue.expected_uuid`
  (`8c6fc098-8cbe-41ae-9689-dd759797a582`); `expected_nfs_version: 3`
  preserved.
- Queue integrity: counts unchanged (completed 5607, failed 204, cancelled 670,
  pending 0, retry 0, keys 8290) and `queue.id` hash unchanged. Archive hash
  unchanged (`b3fc9be9…`).
- Worker `aether`: service active, NFSv3, `rpc.statd` running, NLM lock held;
  `lt queue doctor` all-ok.

## Blockers / not performed

1. **Canary not submitted.** minion-26 mounts `/opt/md2` as NFSv4.2 while the
   preserved producer guard is `expected_nfs_version: 3`, so `lt queue
   path`/`doctor` report an NFS-version mismatch. The producer enqueue path does
   not use mount validation/NLM and the worker host is correctly NFSv3, but the
   task's explicit STOP rule ("do not force an enqueue" on a mount problem) was
   honored. No queue job, archive row, or pending file was written. A decision is
   required: accept the producer-only guard artifact and authorize the canary, or
   authorize a host-appropriate guard/remount change.
2. **nomnom not updated.** SSH from minion-26 and aether returns
   `Permission denied (publickey,password)`; no usable key and Tailscale SSH is
   not enabled. The pipx ref-cli upgrade and routing/status smoke there remain
   outstanding.
3. **Pending backlog not replayed.** Live `transcript-pending.md` is absent.
   The archive has 8,811 historical pending-file rows, 20 failed-execution
   placeholders (reconciler correctly skips them), and 37 `|None` rows. Only
   `|None` rows are selectable by `update_transcript()`; isolated fixture
   confirmed. Safe recovery needs a follow-up coding task; no archive rewrite or
   bulk replay was done.

## Backups / rollback

Backup dir:
`/home/draeician/.local/share/ref-services/deploy-backups/20261109T234313Z-deploy-remote-api-queue-fix`
(config, service unit, pipx metadata, archive copy with matching sha256,
`queue.id` copy, package inventories, deployed wheel, dev129 rollback wheel).
Exact restore commands are recorded in the task file.

## Remaining production actions (separately authorized)

1. Resolve the NFS-version guard mismatch and authorize/run the bounded canary.
2. Gain nomnom access and deploy the pipx ref-cli; verify `--version`,
   `--status`, and HTTP routing.
3. Approve a follow-up recovery task for the pending backlog; do not bulk replay.
4. Verify worker processing and terminal transcript results from the canary.

---

# HANDOFF — f7774dc0 remote-client routing and queue producer

**Date:** 2026-11-09 (UTC)
**Task ID:** `f7774dc0`
**Owner:** OpenCode
**State:** DONE (code merge phase) — production deployment **not** authorized
**Branch:** `fix/remote-api-queue-producer` (merged and deleted)
**Base:** `origin/main` = `377dc34160a78d7e8c601dbad3bdeb7a92f2f7a8`
**Approved head:** `0ec4d5847b1494e9ef347d4a821a89fd0604e6b5`
**PR:** #33 — https://github.com/draeician/ref/pull/33
**Merge commit:** `f939efe4ac4e574a8e4f1b5991c85bd96822e4d6`
**Final main:** `f939efe4ac4e574a8e4f1b5991c85bd96822e4d6`
**Authorization:** Merged after independent review approval. No production
deployment, host upgrade, live config change, queue mutation, or service restart.

## Scope

Fix Incident A (a remote `ref` client fell into the local archive-writer path and
raised `DefaultCredentialsError`) and Incident B (transcription producer
reporting after archive capture succeeded: Deno warning, queue UUID mismatch,
and ambiguous pending-file fallback).

## Root causes

### Incident A — wrong execution path on a remote client

`main()` bootstrapped `~/references`, migrated `references.md`, and enabled file
logging before any routing decision. `run_ingest`, `run_file_ingest`,
`run_search`, `run_transcript`, and interactive mode each fell back to local
processing when `api_url` was unset. The local YouTube path called
`googleapiclient.discovery.build(..., developerKey=None)`, and `__main__`
prompted for `YOUTUBE_API_KEY`. A remote client therefore attempted to become
the archive writer and raised `DefaultCredentialsError`.

### Incident B — stale producer configuration, not a ref code defect

On `minion-26`, archive capture and enrichment succeeded, but the ref-api queue
producer invokes the installed `lt` 0.7.0 with an explicit `--queue-dir`.
`local_transcribe.resolve_queue_dir()` still applies
`queue.expected_uuid` from `~/.config/local-transcribe/config.yaml` even when a
path is supplied. That config is a stale smoke-test pin
(`/tmp/lt-smoke-queue-59553`, `6a058908-116f-41c9-987f-d5f4ef38667e`), while the
real queue identity is `8c6fc098-8cbe-41ae-9689-dd759797a582`. The Deno warning
is a separate stale-version effect: 0.7.0's root Typer callback probes Deno for
every subcommand.

## Decisions and rejected approaches

- All normal CLI ingest/search/list/url-dump/transcript operations require
  `ref-api`; there is **no** local fallback, even on the archive host. Explicit
  `--backup`/`--integrity` remain local server operations.
- Routing uses a non-mutating config read and runs before archive bootstrap,
  migration, file logging, metadata, Google, queue, or enrichment work.
- Removed the startup `YOUTUBE_API_KEY` prompt. Server-side metadata raises a
  controlled `YouTubeCredentialsError`.
- Pending-file fallback is labelled **not queued**; multiline `lt` stderr is
  collapsed to a bounded one-line reference value and kept in full in logs.
- **Rejected:** overwriting `queue.id`, disabling identity validation,
  initializing a replacement queue, deleting jobs, forcing a producer onto
  another queue, or editing live config.
- **Rejected:** changing `local_transcribe.resolve_queue_dir()` so `--queue-dir`
  bypasses `expected_uuid`. Task 043 documents that fail-closed pinning as
  intentional; the defect is the stale live config.
- **Rejected:** installing Deno on a non-worker or prompting for credentials on
  a remote client.

## Files changed

- `src/ref_cli/cli.py` — lazy file logging, non-mutating routing read, exact
  missing-API guidance, pre-bootstrap remote dispatch, `run_interactive`,
  controlled credential error, queue-failure sanitization.
- `src/ref_cli/api_client.py` — file-ingest skip patterns use the non-mutating
  routing config.
- `src/ref_cli/config/config.yaml.template`,
  `src/ref_cli/config/default_config.yaml` — document required API routing.
- `tests/test_remote_client_routing.py` — new routing/credential/server tests.
- `tests/test_cli_api_routing.py`, `tests/test_url_dump_api_cli.py`,
  `tests/test_transcript_block.py`, `tests/test_transcript_blocking.py`,
  `tests/test_transcript_queue_modes.py`,
  `tests/test_transcript_reconcile.py`, `tests/test_server_install.py` — updated
  and new regressions.
- `.codex/AGENTS.md` — durable `wip/ → review/ → done/` lifecycle rule.
- `.codex/tasks/review/f7774dc0-remote-api-queue-producer.md` — task record.
- `HANDOFF.md` — this section.

## Read-only production findings (minion-26, 2026-11-09)

- Queue `/opt/md2/music/youtube/transcripts/transcription-queue`; `queue.id`
  UUID `8c6fc098-8cbe-41ae-9689-dd759797a582` (created by `nomnom`).
- `~/.config/ref/ref-api.env` correctly pins that UUID/path and
  `REF_YOUTUBE_TRANSCRIPT_MODE=local_only`.
- `~/.config/local-transcribe/config.yaml` is stale:
  `queue.path: /tmp/lt-smoke-queue-59553`,
  `expected_uuid: 6a058908-116f-41c9-987f-d5f4ef38667e`.
- Installed `lt`: `local-transcribe 0.7.0`, VCS
  `25b89f1326751a3b0781051331822c50ffde3b19`, pipx venv
  `/home/draeician/.local/share/pipx/venvs/local-transcribe`.
- `local_transcribe/main`: `0.8.1` at
  `b3cf22ee5da337fab9dcd37fb97506f5beab012b`; Deno fix commits `0e83077`,
  `8423007`, `6a2078d`; focused suite includes
  `tests/test_deno_startup_warnings.py`.
- ref-api service unit has `EnvironmentFile=-/home/draeician/.config/ref/ref-api.env`,
  no drop-ins; `ExecStart=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000`.
- Read-only `ref --status` on the host: `Mode: remote`,
  `api_url: http://127.0.0.1:8000`, `Status: ok`.
- Pending-file finding: `transcript_reconcile` only matches durable placeholders
  (`queued for local-transcribe worker`, `already in transcription queue`).
  `transcript-pending.md` entries are **not** automatically recovered/retried;
  restore the queue/config and run `ref --transcript` explicitly.

## Exact verification evidence

| Check | Command | Result |
| --- | --- | --- |
| Full suite | `python -m pytest -q` | **594 passed, 1 warning** (13.90s) |
| Focused routing/queue/reconcile | `pytest -q tests/test_remote_client_routing.py tests/test_cli_api_routing.py tests/test_url_dump_api_cli.py tests/test_transcript_queue_modes.py tests/test_transcript_reconcile.py tests/test_server_install.py` | **109 passed** |
| LT focused | `TERM=dumb NO_COLOR=1 python -m pytest -q tests/test_queue_paths.py tests/test_cli_queue.py tests/test_deno_startup_warnings.py` | **60 passed** |
| Syntax/command gate | `uvx ruff check --target-version py312 --select E9,F63,F7,F82 <changed files>` | **All checks passed** |
| Bytecode | `python -m compileall -q src/ref_cli src/ref_api tests/test_remote_client_routing.py` | exit 0 |
| Build | `uv build` | wheel + sdist built |
| Wheel smoke | clean venv + `pip install dist/ref_cli-*.whl` | `ref <url>` exits 1 with guidance, creates no dirs |
| Missing API CLI | temp HOME + `python -m ref_cli.cli https://example.com/a` | exit 1, exact guidance, no dirs created |
| Unreachable API | `REF_API_URL=http://127.0.0.1:9` | exit 1, connection error, no dirs, no local fallback |
| HTTP-only smoke | local HTTP server + CLI | POST `/urls` body kept original URL; no local dirs |
| Server host status | `python -m ref_cli.cli --status` | `Mode: remote`, `Status: ok` |
| LT simulation | temp queue + stale config | stale `expected_uuid` → exit 1 mismatch; corrected config → `lt queue add` enqueued; no Deno warning with Deno absent from PATH |
| Whitespace | `git diff --check` | clean |
| Secret scan | regex over `git diff` | 0 credential-shaped matches |

## Review corrections (2026-11-09, PR #33)

Review of head `0c73cc8d2cd0999a37ccf2a5186a6e18155d6937` found three defects,
corrected here without changing the documented read-only production findings.

### 1 — `ref --status` treated missing API as local mode

- `api_client.report_api_status()` now reports
  `Mode: unconfigured (api_url is not set)` and
  `Status: error (no ref-api endpoint configured)`, prints server/client setup
  steps (`ref --install-server`, `api_url: http://SERVER_LAN_IP:8000`,
  `export REF_API_URL=...`, `ref --status`), and returns **1**.
- Healthy configured API still returns 0; configured-but-unreachable API
  returns 1.
- Regressions: `tests/test_api_client.py` missing/healthy/unreachable;
  `tests/test_remote_client_routing.py` main-level status tests assert exit
  codes and that no `.config`/`references` files are created.

### 2 — Deno guidance hid the actionable queue error

- Added `_summarize_queue_cli_stderr()`: the full original stderr is still
  logged by `_enqueue_via_lt_cli`; the saved reference gets a bounded one-line
  summary that starts at the first strong queue/UUID/mismatch/identity line and
  drops Deno guidance lines. Unrelated errors are not filtered by the Deno
  check unless a stronger queue line exists.
- UUID validation and the pending-file "not queued" fallback are unchanged.
- Regression `test_lt_failure_saved_reference_prefers_queue_error_over_deno_guidance`
  replays the full original stderr block, asserts the saved status contains the
  mismatch and both UUIDs, contains no Deno install guidance, is one line and
  bounded, says "not queued", names `transcript-pending.md`, and that the full
  stderr remains in the log.

### 3 — README described API as optional

- README now states normal ingestion/search/listing/url-dump/transcript require
  `ref-api`; `api_url` is not optional; missing API never means local CLI
  ingestion; `ref --status` reports unconfigured as an error; the API remains
  the authoritative writer; explicit local backup/integrity/management commands
  keep their behavior; remote clients need no Google credentials, Deno, Whisper,
  or worker. Historical pre-API installs are kept in a separate legacy note.

### Correction verification (actually run)

| Check | Command | Result |
| --- | --- | --- |
| Focused | `pytest -q tests/test_api_client.py tests/test_remote_client_routing.py tests/test_transcript_queue_modes.py` | **59 passed** |
| Full suite | `python -m pytest -q` | **597 passed, 1 warning** (13.71s) |
| Syntax | `python -m compileall -q src tests` | exit 0 |
| Build | `python -m build --wheel` | wheel built (`1.6.12b1.dev150+g0c73cc8d2`) |
| CLI smoke — missing API | clean venv, empty `HOME`, `ref --status` | exit **1**, unconfigured guidance, **no files created** |
| CLI smoke — healthy API | local `/health` server + `REF_API_URL` | exit **0**, `Status: ok`, **no files created** |
| CLI smoke — unreachable API | `REF_API_URL=http://127.0.0.1:18998` | exit **1**, `Status: unreachable`, **no files created** |
| Whitespace | `git diff --check` | clean |
| Secret scan | regex over `git diff` | no credentials (only `YOUTUBE_API_KEY` variable name) |

## Risks and limitations

- Installed `lt` 0.7.0 still prints the Deno warning until a separately
  authorized upgrade to `local_transcribe/main` (0.8.1+).
- The stale `local-transcribe` config still fails identity validation until a
  separately authorized config correction. ref now reports that once, concisely.
- The project's `requires-python` metadata still says `>=3.7`, while existing
  code and tests use newer syntax; the CI target is Python 3.12.
- No production deployment, config edit, queue mutation, service restart, or
  merge was performed.

## Commits and PR

- Implementation: `2ccde1d60f27224ade641fdd77de4590634c1e80`
- Tests: `4e86bd5d1206b84513b783db2c0d3bf9c155dc08`
- Task/handoff/agent docs: `ed60037ba294db7617e6e32e846bc39f7af273c3`
- Review-state task move + evidence: `cb81789e735b38722664c7bbecbadcce492f9b87`
- Draft PR #33: https://github.com/draeician/ref/pull/33
- Exact-head CI for `cb81789`: workflow `tests`, run `42689895217`,
  conclusion **success** (37s).
- This HANDOFF update is a docs-only follow-up commit; PR #33 checks the final
  head after it is pushed.

### Merge closure (2026-11-09)

- Approved head: `0ec4d5847b1494e9ef347d4a821a89fd0604e6b5`.
- Pre-merge exact-head CI: workflow `tests`, run `42692542822`, **success**.
- PR #33 marked ready, merged with a **normal merge commit** (no squash, rebase,
  or force-push).
- Merge SHA: `f939efe4ac4e574a8e4f1b5991c85bd96822e4d6`; parents
  `377dc341…` (main) and `0ec4d584…` (approved head).
- Final `main` SHA: `f939efe4ac4e574a8e4f1b5991c85bd96822e4d6`.
- Post-merge `main` CI: workflow `tests`, run `42694120987`, head
  `f939efe4…`, **success**.
- Task moved to `.codex/tasks/done/f7774dc0-remote-api-queue-producer.md` with
  State **DONE** for the code/merge phase. Closure records land through a
  dedicated documentation branch/PR; nothing is committed directly to `main`.
- Local and remote `fix/remote-api-queue-producer` branches deleted after merge;
  tracking refs pruned. Unrelated branches `docs/unified-ref-consolidation-plan`
  and `fix/youtube-auto-show-notes-api` were preserved.

## Outstanding deployment steps (separately authorized, do not run here)

1. Back up and correct the live `~/.config/local-transcribe/config.yaml`:
   `cp ~/.config/local-transcribe/config.yaml ~/.config/local-transcribe/config.yaml.bak-$(date -u +%Y%m%dT%H%M%SZ)`,
   then set `queue.path` to
   `/opt/md2/music/youtube/transcripts/transcription-queue` and
   `expected_uuid` to `8c6fc098-8cbe-41ae-9689-dd759797a582`. Keep
   `expected_nfs_version: 3` for the fail-closed worker guard.
2. Upgrade the installed `lt` on `minion-26` from 0.7.0 (`25b89f1`) to
   `local_transcribe/main` (0.8.1 at `b3cf22e` or newer) so the Deno probe is
   download-path only. Exact pipx command:
   `pipx install --force 'git+https://github.com/draeician/local_transcribe.git@b3cf22ee5da337fab9dcd37fb97506f5beab012b'`
   (or `pipx install --force .` from a checked-out, verified `main`).
   Verify with `lt --version` and
   `lt queue path --queue-dir /opt/md2/music/youtube/transcripts/transcription-queue`.
3. Restart `ref-api.service` and verify a controlled enqueue against the real
   queue (one deliberately chosen URL; confirm a pending execution and no Deno
   warning).
4. Recover any `transcript-pending.md` entries with `ref --transcript` after the
   queue is healthy.

## Next action

Code merge is complete. The following remain **outstanding** and require separate
production authorization; production remediation is **not** complete:

1. Deploy the merged `ref` (main
   `f939efe4ac4e574a8e4f1b5991c85bd96822e4d6`) to approved hosts.
2. Correct the stale `~/.config/local-transcribe/config.yaml` on `minion-26`
   after re-validating the authoritative queue UUID
   (`8c6fc098-8cbe-41ae-9689-dd759797a582`).
3. Upgrade installed `lt` 0.7.0 (`25b89f1`) to a verified 0.8.1
   (`b3cf22e` or newer).
4. Verify a successful enqueue without the Deno warning.
5. Recover pending transcript URLs safely.
6. Verify actual worker processing and completion.

Do not upgrade ref/`lt`, change queue config or `queue.id`, restart services,
modify transcription jobs, replay pending URLs, or modify production archives
without separate authorization.

Reference: `docs/plans/unified-ref-consolidation.md` on
`docs/unified-ref-consolidation-plan` (PR #29) motivates the single authoritative
`ref-api` client/server split. This task implements the remote-client routing
piece without changing that plan's unrelated scope.

---

# HANDOFF — YouTube transcript routing investigation

**Date:** 2026-10-27 (UTC)
**Mode:** PR #22 deployed to production with verification. One manual smoke capture was submitted; no backlog import or worker configuration change was made.
**Repository:** https://github.com/draeician/ref  
**Scope:** why recent YouTube ingests are routed to local-transcribe/Whisper instead of using captions directly, and the production rollout of the durable queue fallback.

## Executive diagnosis

**Primary cause (confirmed): YouTube is blocking direct caption retrieval from `minion-26`.** A controlled single-video test at **2026-10-26T18:13:09Z** returned `youtube_transcript_api._errors.IpBlocked` after 1.257s. `IpBlocked` is a subclass of `RequestBlocked` and represents an IP-level block; this library raises it for HTTP 429 or a reCAPTCHA challenge page. The numeric status was not exposed. The block began by **2026-10-26T00:38:09Z** and was still active at 18:13Z. The cooldown then suppressed every subsequent transcript provider call for one hour; each recovery probe was blocked again, so the cycle repeated at 05:46, 11:30, 12:31, and 14:37 UTC.

**Secondary cause (high confidence): the local-transcribe queue is not reachable from the running service.** The service virtualenv does not contain `local_transcribe`, and the systemd service `PATH` does not contain `lt`; `lt` also has no configured queue path on this host. Every failure therefore takes the final fallback: append to `transcript-pending.md`. No new local-transcribe/Whisper queue job has been created since **2026-10-24T21:03:29Z**, and none of the recent sample video IDs appear in the queue. The corrective implementation adds explicit absolute `lt`/queue configuration, queue identity verification, and a `local_only` mode so the producer does not need `local_transcribe` installed in its own venv. **Deployed to production on 2026-10-27.**

**Latent defect (high confidence): the enhanced `get_transcript.py` handler is not packaged and cannot be imported in production.** `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the running service. The legacy provider path still worked until the IP block, so this is not the trigger, but it removes the enhanced path and contributes to poor diagnostics.

**Diagnostics gap (high confidence): production logs hide the provider exception.** The controlled test identified `IpBlocked`, but the running service logs only the generic cooldown warning; it does not record the exception class/message. The test also confirmed that the exception object does not expose a numeric HTTP status.

## Phase 3 — automatic transcript reconciliation (implemented, not deployed)

**Status:** Implemented and tested on a feature branch; **no production deployment,
service restart, or live archive modification was performed under this task.**

The storage-related findings below are **superseded** by the verified migration:
Aether now has a symlink from `~/references/transcripts` to
`/opt/md2/music/youtube/transcripts`, and the 542 missing `.generations` files
were copied with SHA-256 verification and zero conflicts. `minion-26` can read
all three smoke-test transcript JSON files. The remaining work was stale queued
placeholders in `references.md`.

### Implementation

- Core reconciler: `src/ref_cli/transcript_reconcile.py`.
- API lifecycle: startup pass plus periodic pass in `src/ref_api/service.py`;
  started/stopped by the FastAPI lifespan in `src/ref_api/app.py`.
- Only rows containing `queued for local-transcribe worker` or
  `already in transcription queue` with an execution UUID are considered.
- Only the referenced execution ID is loaded from the queue state directories;
  historical completed jobs are never enumerated.
- Requires `status: completed`, matching execution `source_key`/`source` video,
  a valid execution generation, and a matching queue key record whose generation
  and `current_execution_id` identify that execution. Missing or conflicting
  generation data is rejected.
- Reads the configured shared `paths.transcripts/<video_id>.json`, never the
  worker-local `output_path`; requires nonempty transcript text and
  `metadata.id == video_id`.
- Replaces only the placeholder field in `extra`, preserving timestamp, URL,
  title, uploader, source, `@meta`, and other extra fields.
- Re-reads/revalidates target rows under the shared archive lock and writes a
  compressed backup before the first change in a pass. Repeated passes are
  idempotent and write nothing when no row changes.
- Queue files are read-only; no re-enqueue, YouTube call, media download, or
  Whisper invocation occurs. `transcript-pending.md` and the 792-URL legacy
  backlog are untouched.

### Configuration

| Setting | Environment | Config key | Default |
|---|---|---|---|
| Enable reconciler | `REF_TRANSCRIPT_RECONCILE_ENABLED` | `transcript_reconcile_enabled` | `true` |
| Interval (seconds) | `REF_TRANSCRIPT_RECONCILE_INTERVAL_SECONDS` | `transcript_reconcile_interval_seconds` | `300` |

The reconciler is a no-op when no durable queue directory is configured. It uses
the existing `REF_LOCAL_TRANSCRIBE_QUEUE_DIR` / `REF_LOCAL_TRANSCRIBE_QUEUE_UUID`
settings and `paths.transcripts`.

### Smoke-test acceptance cases

On the first pass after deployment, these existing completed executions should
replace their placeholders with the corresponding shared transcript JSON paths,
without re-transcription:

| Video ID | Execution ID | Expected transcript |
|---|---|---|
| `jNQXAC9IVRw` | `5d7be5b4-8401-4d4c-a9fd-77081c874b38` | `<paths.transcripts>/jNQXAC9IVRw.json` |
| `0PT5c1z3LL8` | `0e5878f4-af13-4b6d-a43e-2811ecf5be48` | `<paths.transcripts>/0PT5c1z3LL8.json` |
| `RRBN_4L09Mg` | `0b2f2e45-e793-485b-afd2-4d7d71d76f91` | `<paths.transcripts>/RRBN_4L09Mg.json` |

### Deployment and rollback (future, separately authorized)

1. Merge and install the package on `minion-26`; keep the queue settings already
   in `~/.config/ref/ref-api.env`. Optionally add the reconciliation settings.
2. Restart `ref-api.service` in an idle window. Verify `/health` and journal
   lines showing the reconciler started, then confirm only the three placeholder
   rows changed and a `.bak-<timestamp>.gz` backup exists.
3. To roll back behavior without downgrading: set
   `REF_TRANSCRIPT_RECONCILE_ENABLED=false` and restart. To roll back code,
   restore the prior wheel/source revision and restart. Do not restore an archive
   snapshot over newer captures; use the generated backup only if the rewritten
   rows need manual recovery.

Cross-process limitation: the archive lock is process-local. Reconciliation
must run only in the single `ref-api` writer process; a separate CLI process
writing the same archive is outside that lock (pre-existing single-writer model).

## Controlled live test — 2026-10-26T18:13:09Z

Authorized test: exactly one `YouTubeTranscriptApi().fetch("rRtN1pN6KQw")` invocation with zero retries, using the production interpreter and the library directly (not `ref` and not the `/urls` endpoint). No proxy configuration was supplied, so the library's internal retry path was disabled.

| Field | Result |
|---|---|
| Timestamp | Started **2026-10-26T18:13:09Z**; finished **2026-10-26T18:13:11Z** |
| Outcome | **Failure** |
| Exception class | **`IpBlocked`** |
| Exception module | `youtube_transcript_api._errors` |
| Exception MRO | `IpBlocked` → `RequestBlocked` → `CouldNotRetrieveTranscript` → `YouTubeTranscriptApiException` → `Exception` |
| Sanitized message | `Could not retrieve a transcript for the video <url> This is most likely caused by: | YouTube is blocking requests from your IP. This usually is due to one of the following reasons:` |
| Sanitized cause | `YouTube is blocking requests from your IP. This usually is due to one of the following reasons: | - You have done too many requests and your IP has been blocked by YouTube` |
| HTTP status | **Not exposed** (`null` on the exception object). This library raises `IpBlocked` for HTTP 429 or a reCAPTCHA challenge page; the invocation did not expose which condition occurred. |
| Caption segments | Not applicable (failure) |
| Elapsed time | **1.257 s** |
| Preflight | Marker expired (`blocked_until` = 2026-10-26T15:37:13Z), `lease_expires_at` = 0.0, `lease_owner` = null, `next_probe_at` = 0.0; no active transcript/provider probe process; no recent transcript/cooldown journal lines |
| Transcript text | Not printed, downloaded, or archived |

This resolves the earlier `RequestBlocked` vs `IpBlocked` ambiguity: the provider returned **`IpBlocked`**, not the playability-level bot-detection `RequestBlocked` class.

## Pre-deployment production runtime (2026-10-26)

| Item | Verified value |
|---|---|
| Host | `minion-26` |
| Service | `ref-api.service` (systemd user unit), active since 2026-10-26T06:02:30Z |
| Process | PID 1799, `/home/draeician/.local/share/ref-services/ref-api/bin/python .../bin/ref-api --host 0.0.0.0 --port 8000` |
| Python | 3.13.17 (service venv) |
| Package | `ref-cli 1.6.12b1.dev104+g0e5d9828e` |
| Installed source | `file:///home/draeician/.local/share/ref-services/src-ref` (non-editable) |
| Source revision | `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2` — **same as current `origin/main`** |
| `youtube-transcript-api` | 1.2.4 |
| Other relevant deps | google-api-python-client 2.201.0, fastapi 0.161.0, uvicorn 0.54.0, yt-dlp 2026.10.21 |
| `/health` | `{"status":"ok","version":"1.6.12b1.dev104+g0e5d9828e"}` |
| Pipx (not the running service) | `ref-cli` 1.6.12b1.dev104+g0e5d9828e, Python 3.14.4, VCS install at the same SHA; `local-transcribe 0.7.0`; `lt` on the login `PATH` but not on the service `PATH` |
| Service `PATH` | `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin:/snap/bin` — no `~/.local/bin`, so no `lt` |

The deployed source matches `main`; this is not a stale-checkout problem. `ref-api` on `~/.local/bin` points at the pipx venv, but the running unit invokes the dedicated `ref-services` venv directly.

### Enhanced handler import check

- `ref_cli.cli.get_youtube_transcript_with_metadata` is `None` in the service venv.
- `import get_transcript` from the service venv fails with `ModuleNotFoundError: No module named 'get_transcript'`.
- `get_transcript.py` is absent from the installed distribution `RECORD` and from site-packages.
- Cause: `pyproject.toml` packages only `ref_cli` and `ref_api`; the repository-root `get_transcript.py` is not installed. The import shim in `cli.py` only adds the site-packages directory to `sys.path`, so a normal wheel/venv/VCS install cannot import it.

## Cooldown state at diagnosis (historical)

Configured transcripts directory: `/home/draeician/references/transcripts` → `/opt/md2/music/youtube/transcripts`.  
Marker: `/home/draeician/references/transcripts/.youtube-transcript-block.json`.

```json
{
  "blocked_until": 1793029033.066984,
  "duration_seconds": 3600,
  "lease_expires_at": 0.0,
  "lease_owner": null,
  "next_probe_at": 0.0,
  "set_at": 1793025433.066984,
  "version": 1
}
```

- `set_at` = **2026-10-26T14:37:13Z**
- `blocked_until` = **2026-10-26T15:37:13Z**
- At investigation time (~16:06Z) the cooldown was **expired**, no lease was held, and `next_probe_at` was `0.0`.
- The cooldown is re-established only when an actual recovery probe runs and is blocked. Rows during an active cooldown are skipped without a provider call.
- Repeated failures do continually re-establish the cooldown: probes at 12:31:57Z (after the 11:30 cooldown expired) and 14:37:13Z (after the 12:31 cooldown expired) both re-entered a fresh 3600-second block.
- No cooldown state was removed, reset, or edited.

## Timeline evidence

Journal retention begins 2026-10-22T21:55Z.

| Event | Timestamp (UTC) | Evidence |
|---|---|---|
| Last successful direct retrieval | **2026-10-25T18:36:26** | `references.md` row for `rRtN1pN6KQw` with transcript JSON path; JSON mtime 2026-10-25T12:32:18Z. The NFS mount clock is ~6h04m behind the app host (confirmed against the pending file), so the JSON was written at ingest time. |
| First failure after last success / transition | **2026-10-26T00:38:09** | `aZMKzHhlTh8` row becomes `Transcript unavailable (queued in transcript-pending.md)`; same-second cooldown warning. |
| Block warning 1 | 2026-10-26T00:38:09Z | cooldown until 01:38:08Z |
| Block warning 2 | 2026-10-26T05:46:36Z | cooldown until 06:46:36Z |
| Block warning 3 | 2026-10-26T11:30:50Z | cooldown until 12:30:50Z |
| Block warning 4 | 2026-10-26T12:31:57Z | cooldown until 13:31:57Z |
| Block warning 5 | 2026-10-26T14:37:13Z | cooldown until 15:37:13Z |
| Controlled live test | **2026-10-26T18:13:09Z** | `IpBlocked` after 1.257s; no retry; block still active |

There were 10 cooldown warnings total in the retained journal since 2026-10-22, including 5 on 2026-10-24 and 5 on 2026-10-26.

## Last 50 YouTube ingests — measured counts

Sample window: 2026-10-25T14:53:30Z through 2026-10-26T15:05:01Z (last 50 YouTube rows in `references.md`). Classification was correlated with journal cooldown timestamps, transcript JSON presence/mtime, and queue records; it was not inferred from JSON existence alone.

| Category | Count | Share |
|---|---:|---:|
| Direct caption retrieval (JSON path, ingest-time file) | 15 | 30% |
| Actual provider attempt blocked by YouTube | 5 | 10% |
| Skipped during active cooldown (no provider attempt) | 26 | 52% |
| Pending-file fallback, unexplained by cooldown | 3 | 6% |
| Unexpected XML/parse failure (`no element found: line 1, column 0`) | 1 | 2% |
| **Total** | **50** | **100%** |

Additional measurements:

- **34 of 50** rows have a pending-file placeholder.
- **31 of those 34** are post-2026-10-26T00:38; **5** were actual blocked probes and **26** were cooldown skips.
- **0** of the 50 video IDs appear in any local-transcribe queue record.
- **0** new local-transcribe/Whisper jobs were created for this sample.
- Last queue record created: **2026-10-24T21:03:29Z** (`youtube:KHjNVmpHO60`, completed). Queue counts at inspection: pending 0, processing 1, retry 0, completed 1593, failed 183, cancelled 21.
- Pending file: 792 YouTube URLs, last line `https://www.youtube.com/watch?v=VhrtlfTyqp4` (the 15:05Z ingest).

## Failure classification

- **`RequestBlocked` / `IpBlocked` family:** confirmed 5 times in the last 50 (plus 5 earlier warnings on 2026-10-24). The code only records the generic `("blocked", message)` failure and emits one warning, so the historical subclass was not in the journal. The controlled test on the same host/path returned `IpBlocked`, which is the best current classification for this block. In this library, HTTP 429 and a reCAPTCHA challenge both surface as `IpBlocked`; playability-level bot detection surfaces as `RequestBlocked`.
- **`NoTranscriptFound` / `TranscriptsDisabled`:** not explicitly evidenced. The 3 pre-block pending rows (`RPrgNFnbAhQ`, `Jy7FMagiTFk`, `_vaNn_xFS_Y`) could be genuine missing captions, but the logs do not retain the method/message. No `TranscriptsDisabled` or `NoTranscriptFound` text appears in the journal.
- **Network / unexpected:** one row (`_sY20BGB1Tg`, 2026-10-25T15:32:12Z) stores `No transcript available (Legacy method: no element found: line 1, column 0)`. This is an XML/response parse failure, not a confirmed missing caption; it was not queued because the message does not match the no-transcript phrase list.
- **Import error:** enhanced handler `ModuleNotFoundError` is present in production, but it is a packaging defect, not a per-video failure. The legacy path is used.
- **Cooldown skips:** 26 of the last 50 were not provider attempts. `begin_probe()` returned `allowed=False`, and `fetch_youtube_transcript()` returned a synthetic `("blocked", message)`, which then queued/fallback-pended the URL. These are not evidence that captions were unavailable.
- **Local transcription:** no actual Whisper jobs were created for the sample. The fallback file is the legacy pending queue, not the durable local-transcribe queue.

## Exact fallback decisions

1. `fetch_youtube_transcript()` calls `transcript_block.begin_probe(TRANSCRIPTS_DIR)`.
2. During an active cooldown/backoff/lease, `begin_probe()` returns `allowed=False`; no provider call occurs, and the caller receives `("blocked", message)`.
3. `_fetch_youtube_transcript_provider()` also rechecks `is_blocked()` before the legacy fallback, so a block discovered during the enhanced attempt cannot be bypassed by the legacy path.
4. `resolve_transcript_failure_placeholder()` calls `add_url_to_pending_file()` for blocked or no-transcript failures.
5. `add_url_to_pending_file()` tries `local_transcribe.queue_api.enqueue_youtube_safe`; the service venv still does not contain `local_transcribe`, so this raises `ImportError`.
6. It then resolves the explicit `lt` path and queue directory from `REF_LOCAL_TRANSCRIBE_LT` / `REF_LOCAL_TRANSCRIBE_QUEUE_DIR`; as of the 2026-10-27 deployment both are configured and verified, so it invokes `lt queue add --queue-dir` successfully.
7. The reference row becomes `Transcript unavailable (local-only mode; queued for local-transcribe worker; execution <id>)`.

Before PR #22, the service had neither `local_transcribe` nor an explicit `lt`/queue path, so every failure fell back to `transcript-pending.md`. That is no longer the deployed behavior.

## Root cause and unresolved hypotheses

**Established:**

1. The provider returned `IpBlocked` to this host's IP at 2026-10-26T18:13:09Z; the block was already active at 2026-10-26T00:38:09Z and persisted through the controlled test. The cooldown then suppresses all requests for an hour.
2. Every request inside the cooldown is treated as unavailable and sent to the pending-file fallback without a caption attempt.
3. Before PR #22, the service could not reach the durable local-transcribe queue (missing module and missing `lt`/queue config), so failures accumulated in `transcript-pending.md` rather than becoming Whisper jobs. PR #22 was deployed on 2026-10-27 with explicit `lt`/queue configuration and verification; the smoke capture became a durable completed job.
4. The enhanced handler is not importable in any normal installation; production is using only the legacy path.
5. Current logs do not preserve the provider exception class/message or successful retrieval events; the controlled test bypassed this gap by calling the library directly.

**Unresolved:**

- What caused YouTube to classify this IP as blocked (request history vs cloud/provider reputation) is not exposed. The class confirms an IP-level block (`IpBlocked`), but does not distinguish HTTP 429 from a reCAPTCHA challenge page.
- Are the 3 pre-block pending rows genuine missing captions or another failure? Logs are insufficient.
- Are the blocked/skipped videos actually caption-capable? No provider attempt was made for 26 of them, so availability is unknown.
- Is the pending file being imported by the GPU worker? **No.** `queue.legacy_pending_file` remains unset and the worker’s default pending path does not exist; the 792-URL NFS pending file is untouched. This is intentional for this rollout.

There is no evidence that successfully fetched captions are being misclassified as unavailable. The misclassification is limited to (a) cooldown skips being reported as unavailable and (b) non-block unexpected errors being rendered as “No transcript available”.

## Corrective implementation (2026-10-26)

Branch: `fix/durable-transcript-queue` (based on `main` at `53f4c0c`), merged as PR #22 and deployed on 2026-10-27.

- Added `src/ref_cli/transcript_queue.py`: mode resolution, absolute-path validation, queue-directory resolution, `queue.id` parsing, and expected-UUID verification.
- Added `REF_YOUTUBE_TRANSCRIPT_MODE` / `youtube_transcript_mode` with `remote_first` (default) and `local_only`.
- `local_only` reuses an existing transcript JSON or queues the video; it never calls `youtube-transcript-api` and does not read or modify cooldown markers.
- Queue order is in-process `enqueue_youtube_safe` → explicit `lt queue add --queue-dir` → `lt` on `PATH` → `transcript-pending.md`.
- Explicit queue settings: `REF_LOCAL_TRANSCRIBE_LT`, `REF_LOCAL_TRANSCRIBE_QUEUE_DIR`, `REF_LOCAL_TRANSCRIBE_QUEUE_UUID` (and matching config keys). Explicit paths must be absolute.
- CLI output parsing tolerates warnings and ANSI decoration; malformed output fails safely to the pending file.
- Status messages distinguish YouTube block, no captions, local-only skip, durable enqueue, duplicate/already-completed, and pending-file-only fallback.
- Pending-file writes now return a failure result if the file cannot be updated; ref does not claim the URL was recorded when it was not.
- Updated `README.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, and both config templates.
- Added `tests/test_transcript_queue_modes.py` (17 tests) and updated blocking expectations in `tests/test_transcript_blocking.py`.
- Full suite: **406 passed, 1 warning** in the isolated test venv. A post-change wheel build succeeded at `1.6.12b1.dev109+gf158f2d1c` (newer than production `dev104`).

## Worker / backlog findings (read-only)

- Worker host `aether`: PID `2696`, `lt worker run --standby`, systemd user unit `local-transcribe-worker.service`, active since **2026-10-25T15:28:03Z**, holds the NLM lock.
- Worker `state.json` heartbeat at pre-deployment inspection was **2026-10-25T15:28:05Z**. This is normal while idle; the heartbeat updates only when a job is claimed, so it is not a liveness indicator. During the smoke test it updated and showed the active child execution.
- Worker config `/home/draeician/.config/local-transcribe/config.yaml` contains:
  ```yaml
  queue:
    path: /opt/md2/music/youtube/transcripts/transcription-queue
    expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
    expected_nfs_version: 3
    expected_server: depot.draeician.com
    expected_export: /mnt/tank/md2
  ```
- `queue.legacy_pending_file` is unset. The default `~/references/transcripts/transcript-pending.md` does not exist on `aether`.
- The real pending file is `/opt/md2/music/youtube/transcripts/transcript-pending.md` and currently has **792 URLs**. The worker therefore never imports this backlog; it is running, but it is not watching that file.
- Queue counts at inspection: pending 0, processing 1, retry 0, completed 1593, failed 183, cancelled 21.
- Do **not** set `legacy_pending_file` as part of this change: it would immediately import the 792-URL backlog. That requires separate authorization and an explicit capacity/priority decision.

## Production deployment — 2026-10-27

**Status: DONE.** Approved merge commit `30fdc69f1837b28a27d0853ff678a5578816c3ab`; installed package `ref-cli 1.6.12b1.dev111+g30fdc69f1` on Python `3.13.17`.

### Predeployment checks

- `main` clean at the approved merge commit; PR #22 merged; CI `pytest` SUCCESS.
- Prior production: `ref-cli 1.6.12b1.dev104+g0e5d9828e`, source revision `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2`, dedicated venv `/home/draeician/.local/share/ref-services/ref-api`.
- NFS queue mounted read/write at `/opt/md2/music/youtube/transcripts/transcription-queue` (`nfs4`, `depot.draeician.com:/mnt/tank/md2`); `queue.id` UUID matched `8c6fc098-8cbe-41ae-9689-dd759797a582`; 1.2T free (filesystem 99% used).
- `/home/draeician/.local/bin/lt` is `local-transcribe 0.7.0`; `lt queue add --help` includes `--queue-dir`.
- `aether` worker active: PID `2696`, `local-transcribe-worker.service`, started `2026-10-25T15:28:03Z`, NLM lock held. The API was idle (last request was `/health`; no active connections).

### Rollback preservation

Backup directory: `/home/draeician/.local/share/ref-services/deploy-backups/20261027T0035Z-pr22`.

Contains the prior unit, `config.yaml`, freeze, `direct_url` metadata, source revision, old wheel `ref_cli-1.6.12b1.dev104+g0e5d9828e`, queue identity/state/counts, archive hashes/stat metadata, and `show_notes_queue/jobs.json`. Full archive was not copied; `references.md` and pending-file hashes were recorded.

### Configuration and install

- Created `~/.config/ref/ref-api.env` (mode `0600`) with the four approved `REF_*` settings.
- Added `EnvironmentFile=-/home/draeician/.config/ref/ref-api.env` to the existing `ref-api.service`; `systemd-analyze --user verify` passed.
- Checked out `30fdc69f1837b28a27d0853ff678a5578816c3ab` in `/home/draeician/.local/share/ref-services/src-ref` and installed into the dedicated venv with `uv pip install --force-reinstall --no-deps`.
- `ref-api --help` exited 0; installed metadata/module version is `1.6.12b1.dev111+g30fdc69f1`.
- Restarted `ref-api.service` gracefully at `2026-10-27T00:40:39Z` during an idle window (old PID `1799` shut down cleanly; new PID `481515`).
- `/health` returned `{"status":"ok","version":"1.6.12b1.dev111+g30fdc69f1"}`. The running process environment contained all four approved settings.

### Smoke test

One manual `POST /urls` at `2026-10-27T00:42:09Z` for **`jNQXAC9IVRw`** (“Me at the zoo”), which was absent from `references.md` and the queue.

| Field | Result |
|---|---|
| HTTP result | `200`, status `added` |
| Reference status | `Transcript unavailable (local-only mode; queued for local-transcribe worker; execution 5d7be5b4-8401-4d4c-a9fd-77081c874b38)` |
| Execution ID | `5d7be5b4-8401-4d4c-a9fd-77081c874b38` |
| Source key | `youtube:jNQXAC9IVRw` |
| Queue status | **completed** at `2026-10-27T00:42:17Z` |
| Worker visibility | `aether` worker claimed it and ran `yt-dlp` for that execution at `00:42:13Z`; queue record and key record are present |
| Worker output | `/home/draeician/references/transcripts/jNQXAC9IVRw.json` on **aether**, 399 bytes |
| Caption provider | No `youtube-transcript-api` call; status came from the `local_only` branch; no block/provider warnings; cooldown marker remains absent |
| Service errors | No error/exception/traceback markers in the deployment journal window |

**Side effect:** the single submitted URL triggered the existing show-note discovery worker, which automatically added two child YouTube rows and queue jobs:

- `youtube:0PT5c1z3LL8` — execution `0e5878f4-af13-4b6d-a43e-2811ecf5be48` (completed)
- `youtube:RRBN_4L09Mg` — execution `0b2f2e45-e793-485b-afd2-4d7d71d76f91` (completed)

No additional manual captures were run. These child jobs are legitimate output of the existing show-note feature, not a retry of the smoke test. All three queue executions (primary and both children) were completed by the worker.

**Backlog:** `/opt/md2/music/youtube/transcripts/transcript-pending.md` remained unchanged: 792 lines, SHA-256 `ba80807504d6d13c5a495453e04fb8c4f6ee61ba8277e6930e55fcc02f50713d`. No `queue.legacy_pending_file` change was made on `aether`.

## Rollback

Rollback was not required. If needed:

1. Restore `~/.config/systemd/user/ref-api.service` from the backup and remove `~/.config/ref/ref-api.env` (or set `REF_YOUTUBE_TRANSCRIPT_MODE=remote_first`), then `systemctl --user daemon-reload`.
2. Check out `0e5d9828e0f0c51c598bd22fe07239cf4d9f65b2` in `src-ref` and install the preserved old wheel `ref_cli-1.6.12b1.dev104+g0e5d9828e` with `uv pip install --force-reinstall --no-deps`.
3. Restart `ref-api.service` in an idle window and verify `/health` reports `dev104`.
4. Do not restore archive snapshots over newer data. Preserve queue jobs and reference rows; rollback does not remove already-created work.

## Risks and limitations

- `local_only` intentionally disables direct caption retrieval even after YouTube unblocks this IP. Switch back to `remote_first` to resume caption attempts.
- The pipx `lt` is `local-transcribe 0.7.0`; `--queue-dir` support must remain available. A future downgrade would fall back to the pending file.
- Queue identity depends on the NFS mount and `queue.id`; a mismatch or unavailable mount fails safely to the pending file.
- The 792-URL backlog is still not imported. Draining it may create a large burst of local transcription work.
- The worker heartbeat can look stale while idle; check the process/unit and lock, not just `state.json`. During the smoke test it updated and reported the active child execution.
- ~~**Remaining issue:** the worker writes completed transcript JSON to its local `aether:/home/draeician/references/transcripts` path, not the shared NFS archive.~~ **Superseded:** Aether's `~/references/transcripts` now symlinks to `/opt/md2/music/youtube/transcripts`, the missing `.generations` files were copied and SHA-256 verified with zero conflicts, and `minion-26` can read all three smoke-test transcripts. The Phase 3 reconciler consumes the configured shared path rather than the old queue `output_path`.
- The two show-note child jobs completed after the smoke capture; the queue drained cleanly on `aether`.
- The NFS filesystem is 99% used (1.2T free); continued queue growth should be monitored.

## Exactly one recommended next action

**Authorize a separately scheduled production deployment of Phase 3 on `minion-26` (install the merged package, restart `ref-api`, and verify the three smoke-test rows plus the backup), because the reconciler is implemented and tested but this task did not deploy it; do not import the 792-URL backlog or change Aether's worker configuration.**

## Safety

The deployment was explicitly authorized. One manual smoke capture was submitted; it triggered the existing show-note discovery of two child URLs. No direct YouTube transcript probe was made from `minion-26`; no cookies, proxies, bulk requests, backlog import, worker configuration change, worker restart, transcript deletion, or reference deletion occurred. The 792-URL pending file was not modified. The cooldown marker was absent before and after. Configuration, package, queue, and archive metadata were backed up before changes.

## Code change status

PR #22 is merged and deployed. The corrective implementation is active on `minion-26`: configurable `remote_first`/`local_only` mode, explicit durable queue submission, safe pending fallback, tests, and docs. The enhanced `get_transcript.py` packaging defect remains out of scope. The `references.md` parser observation remains non-causal and out of scope.

---

# HANDOFF — `ref --url-dump DOMAIN` read-only domain URL dump (feature)

**Date:** 2026-11-02 (UTC)
**Mode:** **[DONE] — MERGED and DEPLOYED.** PR #26 was merged into `main` as merge commit `dd15d8ad444a91c2f5d81175bdf435c64395c6db` on
2026-11-02T05:30:23Z from reviewed head `b4ad674af5e2f2bc45322067eb8c7a5b620d7633`; CI is green on the merge commit, and the
local and remote feature branches were cleaned up. Deployment was then authorized and completed: `minion-26` now runs
`ref-cli 1.6.12b1.dev129+g80c6e3791` in **both** production environments (pipx CLI venv and dedicated `ref-api` service venv), with
all eleven acceptance checks passing on live production data — see "Production deployment" below.
**Repository:** https://github.com/draeician/ref
**Task file:** `.codex/tasks/3c9a71d4-url-dump-domain.md` (status `[DONE]`, merged **and deployed**)

## What was built

`ref --url-dump DOMAIN` prints every stored URL whose parsed hostname is `DOMAIN` or a subdomain of it, one raw URL per stdout line, newest first. It is a thin client over `GET /urls?domain=DOMAIN` on the configured ref-api (`api_url` / `REF_API_URL`). Matching is label-anchored on the parsed hostname (case-insensitive), never substring; stored URL strings are returned exactly as-is (paths, queries with spaces/unicode, fragments). No matches → exit 0 with empty stdout. Missing config, malformed domain, API error, or network failure → message on **stderr** only and exit 1. Strictly read-only: the CLI dispatch runs before any archive bootstrap/migration, and the server route only parses `references.md`.

## Exact commands and results (all actually run)

- Baseline gate on unmodified `main` (`5565ab59da3179841f8caddc0a54e30df5c1b8ce`):
  `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` → **450 passed, 1 warning in 18.36s**.
- Test env: `uv venv /tmp/opencode/ref-url-dump-venv --python 3.12` (CPython 3.12.15) + `VIRTUAL_ENV=/tmp/opencode/ref-url-dump-venv uv pip install -e ".[api,test]"`.
- Focused feature tests: `pytest tests/test_url_dump_matching.py tests/test_url_dump_api_cli.py -q` → **69 passed**.
- Full gate after changes (same command as CI): `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` → **519 passed, 1 warning in 13.52s** (the one pre-existing StarletteDeprecationWarning).
- `--help` smoke: `--url-dump DOMAIN` renders in usage, options, and epilog.
- Live-server integration (`/tmp/opencode/url-dump-smoke`, uvicorn `--factory 'ref_api.app:create_app'` on 127.0.0.1:8765 with isolated server HOME + seeded temp archive; scripts `run_checks.sh`, `run_checks2.sh`):
  - `curl "http://127.0.0.1:8765/urls?domain=example.com"` → newest-first exact stored strings, subdomains included, `notexample.com` / `example.com.evil.net` excluded; invalid and blank domains → **400** with descriptive detail.
  - `ref --url-dump Example.COM` (isolated HOME + `REF_API_URL`) → exit 0, four pure URL lines on stdout, stderr empty, zero ANSI codes in stdout.
  - No matches → exit 0, both streams empty; unreachable API (`:8799`) → exit 1 with friendly message only on stderr; malformed domain `com` → exit 1 before any HTTP call; missing `api_url` → exit 1 "requires api_url" on stderr, stdout empty.
  - Read-only proof against the **real production archive** (`~/references/references.md`, sha256 recorded before/after): byte-identical after a real-HOME dump run; smoke-server archive sha `283835feee01a8fe30641afca9aecf7920c9c1a7ecc6b9cdaafd998a353e6f0b` unchanged across all requests.
- Secret scan of diff + new files: no secret-like strings (only the pre-existing `spec_tokens` identifier matched the pattern).

## Correction — hostname parsing for scheme-less stored URLs (commit `3e947116cf374dd9912856e2d29dc65bea24b2a3`)

**What was wrong.** `url_hostname()` decided whether a stored value had an authority by testing
`'//' not in text` **anywhere** in the string, and otherwise synthesized a `//authority`. Two
consequences: scheme-less URLs that contain `//` later — an empty path segment or another URL inside
the query — produced no host at all and were silently missing from dumps; values shaped like email
addresses resolved a host through the userinfo of the synthesized authority (`mailto:user@example.com`
and bare `user@example.com` both matched `example.com`).

| Stored value | Before | After (required) |
|---|---|---|
| `example.com/path?q=https://other.com` | no parsed host → not dumped | dumps under `example.com`; never under `other.com` |
| `example.com/foo//bar` | no parsed host → not dumped | dumps under `example.com` |
| `mailto:user@example.com` | matched `example.com` | no hostname, excluded |
| `user@example.com` | matched `example.com` | no hostname, excluded |

**Fix (only `src/ref_cli/domain_match.py`).** Hierarchy is now decided by a leading `scheme://` or a
leading `//`; later `//` stays in the path/query. Opaque schemes (`about`, `blob`, `data`,
`javascript`, `mailto`, `magnet`, `sms`, `tel`, `urn`) and colon-prefixed tokens that are neither
slash-followed nor dotted hosts return no hostname; a scheme-less value whose authority contains `@`
is an email address, not a URL. Preserved unchanged: HTTPS/HTTP matching, userinfo on real URLs,
scheme-less authorities including host:port (`example.com:8443/path`, `//example.com/x`, `[::1]:8000/x`),
trailing-dot/case normalization, label-anchored subdomains, exact stored URL output, and all existing
`normalize_domain` / route 400 / CLI exit-code behavior. No CLI dispatch, API route, or archive code
was touched.

**Tests added (23 cases).** `tests/test_url_dump_matching.py` — the four required regressions, embedded-`//`
host extraction, opaque-scheme/email rejection (`mailto:`, `MAILTO:`, `tel:`, `data:`, `urn:`, `magnet:`,
`user@example.com/reset`), legitimate-authority preservation (userinfo URLs, scheme-less host:port with
embedded slashes), and two archive-level `list_urls_by_domain` checks (exact newest-first dump; empty dump for a
host that only appears inside another host's query). `tests/test_url_dump_api_cli.py` — one `GET /urls?domain=example.com`
route case over an archive seeded with all four values.

**Verification actually run.**

- Focused: `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest tests/test_url_dump_matching.py tests/test_url_dump_api_cli.py -q` → **92 passed, 1 warning in 1.59s**.
- Full repository gate (exact CI command): `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` → **542 passed, 1 warning in 13.36s** — same single pre-existing `StarletteDeprecationWarning`; nothing skipped or weakened.
- Read-only live-server smoke (`/tmp/opencode/url-dump-smoke-fix`, uvicorn `--factory 'ref_api.app:create_app'` on 127.0.0.1:8765, isolated server HOME + freshly seeded archive; `run_checks.sh` → `checks.log`):
  - `curl "…/urls?domain=example.com"` → `["https://docs.example.com/guide/a_b#c", "example.com/path?q=https://other.com", "sub.example.com/foo//bar?q=1#frag", "https://www.example.com/search?q=hello world&x=1#üñîçødé", "example.com/oldest?keep=1"]` — newest first, exact stored strings, embedded-`//` rows included, `mailto:`/email rows and both decoys excluded.
  - `curl "…/urls?domain=sub.example.com"` → only the `sub.example.com/foo//bar?q=1#frag` row; `curl "…/urls?domain=other.com"` → `{"urls":[]}`.
  - Invalid domain → **400** with the original detail text; blank domain → **400**.
  - `ref --url-dump Example.COM` (isolated HOME + `REF_API_URL`) → exit 0, five pure URL lines on stdout, stderr 0 bytes, zero ANSI codes. No matches → exit 0 with both streams empty; unreachable API (`:8799`) → exit 1 with the message only on stderr; malformed domain `com` → exit 1 before any HTTP call; missing `api_url` → exit 1 "requires api_url" on stderr.
  - Read-only proof: smoke archive sha256 `e63590674f03ac39fb41342cb3fccd260fcced949c35a583cefc604867e0fa86` unchanged across every request; real production `/home/draeician/references/references.md` sha256 `5c61ea978b58e390cd2f21f7f359f3b4973b21bf844ce7f59c3e45f2a74c7d35` identical before and after a real-HOME dump run. Server journal showed only `/health`, the `/urls` 200s, and the two expected 400s; no error or traceback lines.
- Secret scan of the diff and changed files: only prose matches plus the synthetic fixtures `https://user:pw@example.com/inbox` and `http://admin:t3st@sub.example.com:8443/p?q=1`; no real secret value.

**Limitations of this verification.** The smoke server ran with `REF_TRANSCRIPT_RECONCILE_ENABLED=false`
so the periodic reconciler could not touch even the temp archive; `/urls` behavior does not depend on that
setting. Only a locally started uvicorn (this task's own process, stopped with `SIGTERM`, port 8765 closed)
served the dumps — no production service was contacted, restarted, or modified, and no real archive was written.
A single-slash malformed value such as `https:/example.com` now yields no host instead of a garbage host; both are
not dumped. Repo/CI has no lint or type gate configured (pytest only), so none was run.

## Pull request and CI verification — PR #26 (2026-11-02)

**Preconditions.** `git fetch origin --prune`; clean working tree; local HEAD = `origin/feat/url-dump-domain` =
`50bfc2f7fa0baaba2221f9988ae5923c62192dbb` (0 ahead / 0 behind); merge-base with `origin/main` equals the main tip
`5565ab59da3179841f8caddc0a54e30df5c1b8ce`, so no rebase and no force-push were needed.

**Documentation-only correction first.** The task-record heading for the hostname fix used `[WIP]` despite being
verified; it now reads `[REVIEW-REQUEST]`. Commit `50bfc2f7fa0baaba2221f9988ae5923c62192dbb` (`[docs] Mark the
hostname-parsing correction review-ready`, 1 file, +1/−1), pushed normally. No implementation or test change.

**PR opened.** `gh pr create --repo draeician/ref --base main --head feat/url-dump-domain --title "feat: Add read-only domain URL dump"` →
**https://github.com/draeician/ref/pull/26**. After CI: state OPEN, base `main` @ `5565ab59`, head @ `50bfc2f7…`,
`mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`, 11 files changed, +1139/−0, auto-merge not enabled, no review requests.

**CI evidence.** Workflow `tests` (`.github/workflows/tests.yml`, the only workflow), run `41391655727`, event
`pull_request`, head SHA `50bfc2f`:

| Command | Result |
|---|---|
| `gh pr checks 26 --repo draeician/ref --watch --interval 15` | `pytest  pass  31s` |
| `gh run view 41391655727 … --json name,headSha,event,status,conclusion` | workflow `tests`, event `pull_request`, headSha `50bfc2f`, status completed, **conclusion success** |
| `gh api …/runs/41391655727/jobs` (steps) | job `pytest` 05:01:55Z → 05:02:26Z; every step `success` |
| pytest step log | **`542 passed, 1 warning in 11.85s`** — same count as the local gate |
| `gh pr view 26 --json statusCheckRollup` | one check `pytest`, `COMPLETED` / `SUCCESS` |

**Re-verification after the documentation commits.** Both documentation-only pushes went normally (no force-push): the
review-ready heading correction `50bfc2f7fa0baaba2221f9988ae5923c62192dbb`, then the evidence commit
`c88f90d11e4e7c74c4e7b7bf09d72988bdb889e9`. That push produced workflow run `41392192743` (`pull_request`, head
`c88f90d`) → **success**; job `pytest` 05:07:41Z → 05:08:14Z, no failed steps, log line **`542 passed, 1 warning in
12.63s`**; `gh pr checks 26 --watch` reported `pytest pass 33s`, and afterwards `mergeable=MERGEABLE` /
`mergeStateStatus=CLEAN` at head `c88f90d…`. Local gate on the same tree: 542 passed, 1 warning.

**CI limitations and blockers.** None block review, but recorded precisely: `main` has **no branch protection**
(`…/branches/main/protection` → 404), so nothing is configured as a *required* check — "all required checks pass" here
means the only CI GitHub reports for this PR (1 of 1) succeeded and merge state became `CLEAN`. Merge state read
`UNSTABLE` while the run was queued. No legacy combined status exists (`commit.status` null). The Actions log carries an
unrelated Node.js 20 deprecation warning for `actions/checkout@v4` / `setup-python@v5`. CI runs a single Python 3.12 job,
matching the local verification interpreter; no lint or type gate is configured in this repository. Every push re-triggers
that same workflow, so reviewers should confirm `gh pr checks 26 --repo draeician/ref` is green against the then-current
head before merging (documentation-only commits after run `41391655727` advance the head again).

**Not done (by instruction).** No merge, no deploy, no service restart, no branch cleanup, no auto-merge enablement;
`README.md` and all feature code were left untouched by this documentation step.

## Merge and branch cleanup — 2026-11-02 (authorized)

Authorization: **merge + branch cleanup approved; deployment NOT authorized.** Repo guides read first: no root `AGENTS.md` or
`project_spec.md`; the conventions live in `.codex/AGENTS.md` and `.codex/AGENTS_WORKFLOW.md`. This section supersedes the
"PR open / awaiting merge authorization" state recorded above.

**Preflight (before merging).**

| Check | Command | Result |
|---|---|---|
| Refs refreshed + stale pruned, tree clean | `git fetch origin --prune`; `git status --short` | no new commits; empty output |
| PR open, mergeable, head equals reviewed SHA | `gh pr view 26 … --json state,isDraft,mergeable,mergeStateStatus,headRefOid,baseRefOid,autoMergeRequest` | `OPEN`, not draft, `MERGEABLE`, `CLEAN`, head `b4ad674af5e2f2bc45322067eb8c7a5b620d7633`, base `main` @ `5565ab59…`, 8 commits, auto-merge null |
| CI green on that exact head | `gh pr checks 26 --repo draeician/ref`; `gh api …/commits/b4ad674…/check-runs` | `pytest pass 41s` (run `41392600076`); check-run on `b4ad674`: completed / **success** |
| No divergence or conflict risk | `git rev-list --left-right --count origin/feat/url-dump-domain...HEAD`; `git merge-base HEAD origin/main` | `0 0`; merge-base = main tip `5565ab59…` |
| Local gate at reviewed head | `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` | **542 passed, 1 warning in 13.23s** |

**Merge.** `gh pr merge 26 --repo draeician/ref --merge` → normal merge commit (no squash, no rebase, no force-push):
**`dd15d8ad444a91c2f5d81175bdf435c64395c6db`**, `Merge pull request #26 from draeician/feat/url-dump-domain`, merged
`2026-11-02T05:30:23Z` by `draeician`.

**Verification after merge.**

| Check | Command | Result |
|---|---|---|
| PR merged | `gh pr view 26 --json state,mergedAt,mergeCommit,mergedBy` | `MERGED`, `2026-11-02T05:30:23Z`, merge commit `dd15d8a…` |
| History preserved (true merge) | `git rev-parse dd15d8a^1 dd15d8a^2` | parents `5565ab59…` + reviewed head `b4ad674…` |
| Reviewed commits reachable from main | `git merge-base --is-ancestor <sha> origin/main` × 8 (`19100a6`, `baba588`, `4240f9b`, `3e947116…`, `58de2f7`, `50bfc2f7…`, `c88f90d1…`, `b4ad674a…`) | all reachable |
| Merged tree == reviewed head | `git diff --stat b4ad674… origin/main` | empty |
| CI green on main after merge | `gh run list --commit dd15d8a…`; jobs API; log grep | workflow `tests`, event **push**, **success**; job `pytest` 05:30:29Z → 05:31:05Z, no failed steps; **`542 passed, 1 warning in 12.89s`** |
| Local gate on merged main | `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` | **542 passed, 1 warning in 13.61s** |

**Cleanup.** `git checkout main`; `git merge --ff-only origin/main` (fast-forward only, `5565ab5..dd15d8a`);
`git branch -d feat/url-dump-domain` → `Deleted branch feat/url-dump-domain (was b4ad674)`; the remote branch was already removed
by GitHub at merge (`[deleted] … origin/feat/url-dump-domain`) and an explicit delete API call returned 404, confirming absence;
`git fetch origin --prune`. Unrelated `origin/fix/youtube-auto-show-notes-api`, the single worktree, and all untracked files were
left untouched. Final state: `HEAD` = `main` = `origin/main` = **`dd15d8ad444a91c2f5d81175bdf435c64395c6db`**, 0 ahead / 0 behind,
clean tree.

**Post-merge documentation path.** Direct commits to `main` are prohibited, so these records were committed on
`docs/record-url-dump-merge-cleanup` (branched at merged main) and opened as **documentation-only PR
https://github.com/draeician/ref/pull/27** (`[docs] Record url-dump merge and cleanup evidence`, base `main`, 2 files, +133/−6),
which was authorized and **merged as `80c6e379106a73c047cd517e56207bc62d558d7f` at `2026-11-02T05:53:37Z`** (normal merge commit,
parents `dd15d8a…` + head `5b23a05…`; post-merge CI push run `41396641392` success). That merge is the approved source of the
deployment below. Documentation only — no code, tests, README, or archive data changed; gate unchanged at 542 passed. Final-head CI
on PR #27 (`5b23a05…`): run `41395309762` success, log line **`542 passed, 1 warning in 12.95s`**.

**Roll back.** Code-level: `git revert -m 1 dd15d8ad444a91c2f5d81175bdf435c64395c6db` — no migration, schema, config, or
archive-data change to unwind. Production-level (after the deployment below): reinstall the preserved `dev117` wheel per
`ROLLBACK.md` in `/home/draeician/.local/share/ref-services/deploy-backups/20261102T1416Z-pr26-url-dump/`; never overwrite newer
reference data.

## Production deployment — minion-26 (authorized, 2026-11-02)

Approved source: `main @ 80c6e379106a73c047cd517e56207bc62d558d7f` (PR #27 merge; CI push run `41396641392` success). Full evidence
tables are in the task file section "[DONE] Production deployment on minion-26"; summary:

- **Actual environments discovered:** the systemd user unit runs `/home/draeician/.local/share/ref-services/ref-api/bin/ref-api`
  (dedicated venv, Python 3.13.17) — **not** the pipx env; and `~/.local/bin/ref` symlinks to that service-venv binary. Service env
  was at `dev117+g5565ab59d`; the pipx venv (Python 3.14.4) had already been upgraded out-of-band at 13:56Z to content verified
  byte-identical to the approved source (full RECORD-vs-git comparison, 35/35 modules), with no logged provenance — reinstalled from
  this deploy's audited wheel regardless.
- **Backup:** `deploy-backups/20261102T1416Z-pr26-url-dump/` — unit/config copies (0600), full service-env freeze, previous wheel
  copy (`dev117`, sha256 `d80ee856…`), archive/backlog/queue/health/journal snapshots, and `ROLLBACK.md`. Archive hashes are
  baselines only: the API reconciler legitimately rewrites `references.md` every ~307 s with its own `.bak-<UTC>.gz`; rollback never
  overwrites newer reference data.
- **Install:** wheel built from a checkout at exactly `80c6e37…` (`uv build --wheel`) → `ref_cli-1.6.12b1.dev129+g80c6e3791-py3-none-any.whl`,
  sha256 `03ee26870ab8c88de129c01d020d6380ebc3bf682778f9c9d8685f462f0fd7da`; installed with `--no-deps` into both envs (approved
  source has zero dependency changes); all 47 non-`ref-cli` deps identical before/after; unit/env/queue config untouched.
- **Restart:** issued `14:20:04Z`, ~4 s after a reconciler cycle completed and while the notes worker was idle; clean uvicorn
  shutdown/startup, new PID 3521265, NRestarts 0, reconciler resumed with first post-restart cycle `updated=0 errors=0`. Only
  `ref-api.service` was restarted.
- **Acceptance (all pass):** CLI + service env report `dev129+g80c6e3791`; `/health` and `ref --status` confirm it live;
  `GET /urls?domain=reddit.com` → 200 with 3,738 URLs **order-identical** to `ref --url-dump reddit.com` stdout (one raw URL per
  line); apex query `youtube.com` includes `www.`/`music.` subdomains while exact-host queries stay scoped; no-match domain → empty
  stdout exit 0; dead API URL via `REF_API_URL` override → stderr + exit 1 with production config untouched; malformed single-label
  domain rejected. Archive mtime predates the restart command, post-restart reconciler cycles changed nothing (`updated=0`), pending
  backlog sha and queue listing unchanged — all smoke traffic was read-only GETs.

## Limits / known behavior (not claimed fixed)

- Single-label/TLD-only dumps (`com`) rejected by design; IDNs must be passed as punycode (`xn--…`).
- Newest-first is a stable sort on the stored timestamp string (ties keep archive order); duplicates preserved.
- Like `--list`/`--status`, config bootstrap may create/merge `~/.config/ref/config.yaml`; read-only guarantee covers archives and server data only.
- Fresh-HOME smoke runs initially hit the pre-existing interactive `YOUTUBE_API_KEY` prompt in `cli.py __main__` (unrelated to this feature); reruns set a dummy env key, mirroring production conditions where the key is configured.
- Stored values that are email addresses or non-web URIs (`mailto:`, `tel:`, `data:`, `urn:`, `magnet:` …) are never dumped, and userinfo only counts on a value with its own hierarchical scheme (correction commit `3e947116`). Scheme-less host:port values still match.

## Exactly one next step

**Reviewer independently verifies the production deployment on `minion-26` (spot-check `ref --version`, `/health`, and a read-only
`ref --url-dump DOMAIN`) and authorizes merging the documentation PR opened from branch `docs/record-url-dump-deploy`** — direct
commits to `main` are prohibited, so this deployment record can only land through that PR. No further production action is pending;
any subsequent change (including rollback per `ROLLBACK.md` in the deploy backup directory) requires separate authorization.

---

# HANDOFF — `ref --upgrade` read-only installation detection and instructions

**Task:** `b1255911` — [fix] Make `ref --upgrade` strictly read-only and topology-aware
**Owner:** OpenCode
**Branch:** `fix/upgrade-instructions-detection`
**Task record:** `.codex/tasks/b1255911-upgrade-instructions-detection.md`
**Application/test commit:** `39d7b3510d6d5da63d31b37fa424ce52d294995f`
**Date:** 2026-11-09 (UTC)

## 1. Original problem and root cause

On `minion-26`, the CLI and API are separate installations. The CLI launcher
`/home/draeician/.local/bin/ref` resolves into the dedicated service venv
`/home/draeician/.local/share/ref-services/ref-api/bin/ref`; a separate pipx
`ref-cli` install also exists. `ref-api.service` runs
`.../ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000`.

The old `ref --upgrade` assumed the running Python environment contained
`pipx_metadata.json`. In the service venv it does not, so the command printed
`Install source: not detected as a pipx venv.` The old command also had an
automatic `perform_upgrade()` path that ran pipx upgrades/injection and restarted
systemd, contrary to the required read-only contract.

## 2. Implementation summary

- Removed automatic installation/upgrade/injection/service-restart execution.
- `ref --upgrade` now resolves the running executable, symlink target,
  interpreter and environment, then reads `ref_cli-*.dist-info`, `METADATA`,
  PEP 610 `direct_url.json`, `INSTALLER`, and `_version.py`.
- Independently enumerates pipx installs from `PIPX_HOME`, XDG data home and
  conventional pipx homes; it does not assume pipx owns the PATH executable and
  works without a `pipx` executable.
- Parses `ref-api.service` `ExecStart`, identifies the service venv/interpreter,
  installed version/revision/source, and whether CLI/API share an environment.
- Queries GitHub once for the default branch and latest commit SHA without
  credentials. Handles unavailable, timeout, rate limit, malformed responses,
  unknown provenance, editable/uncommitted source, and abbreviated SHAs.
- Prints per-installation status, pinned Git upgrade commands, `[api]`
  preservation for service environments, restart requirements, verification
  commands, and rollback guidance.
- Claims `current` only when a revision comparison supports it. Prints
  `Nothing to do` when both installations match GitHub, and addresses only the
  outdated installation when they differ.
- `--upgrade` is dispatched before archive bootstrap/migration. CLI import skips
  `~/references/logs` file handlers for `--upgrade`, so it writes no application
  data.

## 3. Files changed

- `src/ref_cli/upgrade.py` — read-only topology detection, GitHub check,
  comparison, instructions, verification, rollback.
- `src/ref_cli/cli.py` — read-only dispatch/help and read-only logging mode.
- `tests/test_upgrade.py` — 37 regression tests, including real `cli.main()`
  dispatch and no-mutation assertions.
- `README.md` — read-only behavior and split-environment upgrade/restart guidance.
- `.codex/tasks/b1255911-upgrade-instructions-detection.md` — task record.
- `HANDOFF.md` — this section.

## 4. Architectural decisions (Decision Journal)

1. Detection performs **no subprocess calls**; it reads pipx metadata, dist-info,
   PEP 610, and the systemd unit directly.
2. The running environment is derived from the interpreter/executable, not from
   whichever `ref` is first on PATH.
3. pipx and dedicated service venvs are inspected independently; a service venv
   is never assumed to be pipx-managed.
4. A PyPI-only or unknown-provenance install is `unknown`, never falsely
   `current`.
5. Dedicated service upgrades use the service venv's own Python and retain
   `ref-cli[api]`.
6. A local wheel/artifact is not treated as a source repository; missing upstream
   provenance is stated explicitly.
7. Service restart is recommended only when the environment used by
   `ref-api.service` changes.
8. This repo has no `.codex/tasks/wip/` or `review/`; task `3c9a71d4` documents
   the hash-file convention, so review state is recorded in the task file.
9. (2026-11-10, stabilization closure) The proposed additional NFSv3 producer
   mount is **cancelled, superseded, and not authorized**. Keep the existing
   NFSv4.2 producer mount on `minion-26` and the NFSv3/NLM worker mount on
   `aether`; do not install `/mnt/ref-queue-v3`; preserve the shared queue UUID
   `8c6fc098-8cbe-41ae-9689-dd759797a582`; do not weaken NFS/NLM safety
   validation. Cross-protocol producer safety remains unproven and requires a
   separate **read-only** audit.

## 5. Read-only host-specific result on minion-26

The new reporter was run from the development venv with explicit read-only paths.
It did not call pip, pipx or systemctl and changed nothing. It detected:

- CLI environment: dedicated service venv; resolved executable symlink;
  installed revision `80c6e3791`; GitHub main
  `80c6e379106a73c047cd517e56207bc62d558d7f`; status `current`.
- Separate pipx `ref-cli`: source `git+https://github.com/draeician/ref`;
  installed revision `80c6e3791`; status `current`.
- `ref-api`: same environment as CLI; service `ExecStart` correctly identified;
  status `current`.

Both installations are current, so the command prints no reinstall steps.

## 6. Exact verification commands and results

Development environment: `/tmp/opencode/ref-venv` (Python 3.14.4, editable
`.[api,test]`, local-only ruff/build). No global package installs.

| Command | Exit | Result |
|---|---:|---|
| `/tmp/opencode/ref-venv/bin/python -m pytest -q` | 0 | **566 passed, 1 warning in 13.67s** |
| `... -m pytest -q tests/test_upgrade.py tests/test_cli_api_routing.py tests/test_url_dump_api_cli.py tests/test_server_install.py` | 0 | **74 passed, 1 warning in 2.05s** |
| `/tmp/opencode/ref-venv/bin/ruff check --select F,E9,ISC src/ref_cli/upgrade.py tests/test_upgrade.py` | 0 | All checks passed |
| `/tmp/opencode/ref-venv/bin/python -m compileall -q src get_transcript.py` | 0 | Clean |
| `/tmp/opencode/ref-venv/bin/python -c "import ref_cli.cli, ref_cli.upgrade, ref_api.server"` | 0 | Imports OK |
| `/tmp/opencode/ref-venv/bin/python -m build --outdir /tmp/opencode/ref-dist` | 0 | Wheel + sdist built |
| isolated wheel smoke install with `[api]` | 0 | `ref --version` exit 0 |
| isolated fresh-HOME `ref --upgrade` | 0 | Exit 0; **0 files written to fresh HOME** |
| `git diff --check` | 0 | Clean |
| secret scan of changed files | 0 | Only non-secret variable names; no credentials |

No repo-configured ruff/flake8/mypy gate exists. A full default ruff pass reports
pre-existing legacy `cli.py` issues unrelated to this change; targeted
changed-file checks pass.

## 7. Failed checks and unresolved limitations

- No required check failed.
- PyPI-only installs without a SHA or `direct_url.json` remain `unknown`.
- Local wheel artifacts cannot reveal their upstream repository; output states
  this and offers only a conditional SHA-pinned Git reinstall.
- Editable installs compare the recorded commit but not uncommitted changes.
- GitHub network failure/rate limiting/timeout degrades status to `unknown`.
- The old production binary still contains the mutating implementation until this
  branch is reviewed and separately deployed. Do not run the old
  `ref --upgrade` in production.

## 8. Installation compatibility findings

Confirmed by read-only inspection on `minion-26`: CLI launcher symlink into a
dedicated service venv, separate pipx VCS install, dedicated service venv with
PEP 610 artifact provenance, user systemd unit with an explicit `ExecStart`, and
identical CLI/API revision `80c6e3791`. Missing metadata, corrupt pipx metadata,
PyPI, local repository, editable, local wheel, missing pipx executable, missing
service, unreadable unit, GitHub failure/rate limit/timeout, abbreviated SHAs,
split versions, current-both, only-one-outdated, unknown provenance, `[api]`
retention, and no-mutation behavior are covered by tests.

## 9. Git, push, and task status

- Branch: `fix/upgrade-instructions-detection`
- Application/test commit: `39d7b3510d6d5da63d31b37fa424ce52d294995f`
- Task status: IN-REVIEW; task record at
  `.codex/tasks/b1255911-upgrade-instructions-detection.md`
- No merge, deployment, production package change, virtualenv modification, pipx
  mutation, `ref-api` restart, or host configuration change occurred.

## 10. Final branch head and push verification

- Application/test commit: `39d7b3510d6d5da63d31b37fa424ce52d294995f`
- Evidence/documentation commit: `e5155acc6194bfb2e7090dd51a088f2676b03240`
- Verified remote head before this final record update: `5e6367a0bc12bdcfacb8f1efdebe3914cba99ad6`
- Branch: `fix/upgrade-instructions-detection`
- All commits are pushed to `origin`. This final handoff commit only records the
  already-pushed head; the exact remote head after it is verified with
  `git rev-parse origin/fix/upgrade-instructions-detection` and reported in the
  delivery message to Drae.
- Working tree was clean before this final record update; no merge or deployment
  occurred.

## 11. Exactly one next step

Reviewer inspects the pushed branch, task record, HANDOFF, diff and test evidence;
then authorizes or declines a separately scoped merge/deployment. Do not merge or
deploy under this task.

## 12. Review corrections — running API, Git ancestry, lifecycle, CI (2026-11-09)

**Branch:** `fix/upgrade-instructions-detection`
**Owner:** OpenCode
**Task:** `b1255911` — now at `.codex/tasks/review/b1255911-upgrade-instructions-detection.md`, State `REVIEW`
**Authorization:** correct the branch, verify, commit, push, open a draft PR. **No merge, deployment, production package change, or service restart.**

### Defects found in review and their corrections

1. **Running API was never inspected.** The first implementation compared only the
   installed ref-api package. It now performs one bounded, read-only
   `GET /health` (2 s timeout). Installed revision, running revision, and GitHub
   default-branch revision are reported separately. Running state is
   `current` / `stale` / `unknown`; unreachable or unreadable responses are
   `unknown`, never `current`. A stale running process with current installed code
   produces only a user-controlled `systemctl --user restart ref-api.service`
   instruction. The reporter never restarts anything.
2. **Any differing SHA was treated as outdated.** `compare_revisions()` now
   returns only `exact` / `different` / `unknown`. GitHub commit resolution plus
   the compare API classify the relationship as `exact` / `behind` (outdated) /
   `ahead` / `divergent` / `unknown`. Abbreviated SHAs are resolved to full SHAs
   first. `ahead` and `divergent` explicitly say "do not downgrade"; missing
   GitHub evidence and unresolved abbreviations are `unknown` with no command.
3. **Status and directory disagreed.** The task now follows
   `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`. The record
   was moved with `git mv` (history preserved) into `review/`, and its State is
   `REVIEW`.
4. **No remote CI run for the branch head.** A draft PR against `main` triggers
   the existing `pull_request` workflow. The exact pushed head is verified below.
   The PR is not merged and CI protections are unchanged.

### Architectural decisions

- `/health` is read-only and bounded. Endpoint precedence: explicit argument,
  configured loopback `api_url`, then `ExecStart`-derived service URL. Non-loopback
  configured URLs are ignored.
- The running process is compared with the installed package, not with GitHub, so
  a running-stale recommendation is independent of whether an upgrade is needed.
- Revision ancestry requires GitHub evidence. A SHA difference alone is never a
  downgrade recommendation; when evidence is missing the result is `unknown`.
- `unknown` runtime or revision adds an unresolved status, so the report cannot
  print "Nothing to do" or claim a service is current.
- Lifecycle status lives in both the directory and the record; they must agree.

### Exact verification (all commands actually run)

Environment: `/tmp/opencode/ref-venv` (Python 3.14.4, editable `.[api,test]`).

| Command | Exit | Result |
|---|---:|---|
| `python -m pytest -q` | 0 | **576 passed, 1 warning in 13.64s** |
| `python -m pytest -q tests/test_upgrade.py` | 0 | **47 passed in 1.35s** |
| `python -m pytest -q tests/test_upgrade.py tests/test_cli_api_routing.py tests/test_url_dump_api_cli.py tests/test_server_install.py` | 0 | **84 passed, 1 warning in 2.20s** |
| `ruff check --select F,E9,ISC src/ref_cli/upgrade.py tests/test_upgrade.py` | 0 | All checks passed |
| `python -m compileall -q src get_transcript.py` | 0 | Clean |
| `python -c "import ref_cli.cli, ref_cli.upgrade, ref_api.server"` | 0 | Imports OK |
| `python -m build --outdir /tmp/opencode/ref-dist` | 0 | Wheel + sdist built |
| isolated venv + `ref_cli[...][api]` wheel install | 0 | `ref --version` exit 0 |
| isolated `HOME=<fresh> ref --upgrade` | 0 | Exit 0; **0 files written to fresh HOME**; ahead, no downgrade |
| `git diff --check` | 0 | Clean |
| secret scan of changed files | 0 | Only `--host`/`--port` tokens; no credentials |

Real read-only checks (no mutation, no restart):

- minion-26 report: installed/running/GitHub all `80c6e3791`; runtime
  `current`; `Nothing to do`.
- `5b23a05` → `behind` (1 commit).
- `39d7b3510` → `ahead` (1 commit), no downgrade.
- `234b6747f` → `ahead` (4 commits), no downgrade.

### Git, commit, and CI

- Review-correction application/test commit:
  `63395ce84c00a2684e8532b2e227e9c0f05d2d80`
- Documentation/task/lifecycle commit pushed for CI:
  `903e89b8a88fc1142cbedbbc2f9638888fb8e5e7`
- Prior remote head preserved: `234b6747fc4686a9515410beef25fb643cde9d9b`
- Branch: `fix/upgrade-instructions-detection`
- Draft PR: https://github.com/draeician/ref/pull/30 (base `main`, draft, open;
  not merged)
- Exact-head CI: workflow `tests`, event `pull_request`, run `42660825495`,
  head `903e89b8a88fc1142cbedbbc2f9638888fb8e5e7`, conclusion **success**
  (pytest job 35s).
- CI protections were not changed. The workflow runs on `pull_request`; the branch
  push alone had no run, which is why the draft PR was required.

### Unresolved limitations

- Running-state classification needs a `/health` version containing `+g<sha>` (or
  a matching package version); otherwise it stays `unknown`.
- Relationship classification needs resolvable GitHub evidence; PyPI-only installs,
  unresolvable abbreviations, and GitHub outages stay `unknown`.
- Local wheel artifacts cannot reveal their upstream repository; the report states
  this and offers only a conditional SHA-pinned Git reinstall.
- Editable installs compare the recorded commit, not uncommitted changes.
- No production restart or deployment was performed under this task.

### Status and next action

Task `b1255911` is `REVIEW` in `.codex/tasks/review/`. The next action is reviewer
inspection of the draft PR, exact-head CI, diff, and this handoff. Do not merge or
deploy until that review is complete.

## 13. Merge, task closure, and branch cleanup — PR #30 (2026-11-09)

**Authorization:** Drae explicitly authorized merging PR #30, completing the task
lifecycle, updating HANDOFF.md, and cleaning up the feature branch. Production
deployment, package upgrades, virtualenv changes, service restarts, and
local-transcribe configuration changes were **not** authorized and did not occur.

**Merge record**

- Reviewed PR: #30 — https://github.com/draeician/ref/pull/30
- Base: `main`
- Approved feature SHA: `a91cf697d83a1a4a9dfe79edef34598cccc4dd55`
- Merge strategy: normal merge commit (no squash, rebase, or force-push)
- Actual merge commit: `22255c4e6d5ae37f3ce41eafa7f8dfc7ff33f887`
- Merge timestamp: `2026-11-09T18:53:27Z`
- Pre-merge CI on approved SHA: workflow `tests`, event `pull_request`, run
  `42661037854`, conclusion **success**
- Post-merge CI on exact main merge commit: workflow `tests`, event `push`, run
  `42678087181`, head `22255c4e6d5ae37f3ce41eafa7f8dfc7ff33f887`, conclusion
  **success**

All reviewed commits are reachable from `main`: `39d7b35` (implementation),
`e5155ac` (first evidence), `5e6367a` and `234b674` (prior head records),
`63395ce` (review corrections), `903e89b` (review-correction lifecycle record),
and `a91cf69` (draft PR/CI record). The merged `main` tree contains
`check_running_api` and `resolve_revision_relationship` in
`src/ref_cli/upgrade.py`, the 47-test upgrade suite, and the reviewed task record.

**Task status and location**

- Task `b1255911`: **DONE**
- Location: `.codex/tasks/done/b1255911-upgrade-instructions-detection.md`
- Lifecycle: `wip/` (active) → `review/` (review) → `done/` (accepted, merged)

**Branch cleanup results**

- Remote feature branch `fix/upgrade-instructions-detection`: deleted by GitHub on
  merge (observed as `[deleted] ... -> origin/fix/upgrade-instructions-detection`
  during fetch), confirmed absent by `git ls-remote --heads origin`.
- Local feature branch: deleted safely after verifying it was an ancestor of
  `main` (`git branch -d`, was `a91cf69`).
- Local `main`: fast-forwarded `80c6e379` → `22255c4e`; now matches
  `origin/main`.
- Stale remote-tracking refs pruned (`git fetch --prune`, `git remote prune origin`).
- Unrelated branches preserved: `docs/record-url-dump-deploy`,
  `docs/unified-ref-consolidation-plan`, `fix/youtube-auto-show-notes-api`.
- PR #28 and PR #29 remain open and untouched.
- Working tree clean.

**Remaining limitations (unchanged by merge)**

- Running-state classification needs a `/health` version containing `+g<sha>` or a
  matching package version; otherwise it stays `unknown`.
- Relationship classification needs resolvable GitHub evidence; PyPI-only
  installs, unresolvable abbreviations, and GitHub outages stay `unknown`.
- Local wheel artifacts cannot reveal their upstream repository; only a
  conditional SHA-pinned Git reinstall is offered.
- Editable installs compare the recorded commit, not uncommitted changes.

**Production confirmation**

No deployment, pipx upgrade, ref-api virtualenv modification, `ref-api.service`
restart, or local-transcribe configuration change was performed. The merge only
updated the GitHub repository and local Git metadata.

**Exactly one next action**

A separately authorized production deployment may update the CLI/ref-api
installation to merged `main` and, if needed, restart `ref-api.service` under user
control. Do not deploy under this task.

## 14. PR #28 conflict resolution, merge, and cleanup (2026-11-09)

**Authorization:** Drae explicitly authorized resolving PR #28 documentation
conflicts, merging PR #28 into `main`, updating the task record and HANDOFF.md,
and removing the merged feature branch. Production changes were **not**
authorized and did not occur.

**Original deployment:** The November 2 `ref --url-dump` production deployment on
`minion-26` remains documented unchanged above and in the task file section
"[DONE] Production deployment on `minion-26`". This merge did not alter it.

**Conflict resolution**

- PR #28 (`docs/record-url-dump-deploy`, head `5159878…`) was based on
  `80c6e379` and conflicted with `main` at `6e8c33b` in `HANDOFF.md`.
- `origin/main` was merged into the feature branch (no rebase/squash). The single
  conflict was the URL-dump "Exactly one next step": the resolution kept the PR's
  updated November 2 deployment next-step and preserved all later `ref --upgrade`
  sections 1–13 appended on main.
- The task record `.codex/tasks/3c9a71d4-url-dump-domain.md` merged without
  conflict; its existing history, acceptance evidence, deployment evidence, and
  backup/rollback information were preserved.
- Resulting conflict-resolution commit: `42e60247454000a86b11c8595bb4057e84c0b755`
  (`[docs] Merge main into docs/record-url-dump-deploy`).
- Final diff vs `main` was documentation-only: `HANDOFF.md` and
  `.codex/tasks/3c9a71d4-url-dump-domain.md`. No application code, tests,
  dependencies, or configuration changed.

**Verification (all actually run on the resolved tree)**

| Check | Result |
|---|---|
| Full `python -m pytest -q` | **576 passed, 1 warning in 14.34s** |
| Conflict markers in `HANDOFF.md` | none |
| `git diff --check` | clean |
| Main `##` HANDOFF headers preserved | all present |
| Deployment evidence present | `dev129+g80c6e3791`, backup dir `20261102T1416Z-pr26-url-dump`, `ROLLBACK.md` |
| `ref --upgrade` sections preserved | sections 1–13 present |
| Diff vs `main` | only the two documentation files |
| Secret scan of changed docs | no credentials (only the scan-pattern text) |
| PR #28 exact-head CI (`42e6024…`) | run `42679552349`, **success** |

**Merge record**

- PR: #28 — https://github.com/draeician/ref/pull/28
- Reviewed head: `42e60247454000a86b11c8595bb4057e84c0b755`
- Merge strategy: normal merge commit (no squash/rebase/force-push)
- Actual merge commit: `d51f83417b13b83dfbd5f5e8a66f830ff442cb91`
- Merge timestamp: `2026-11-09T19:03:35Z`
- Post-merge CI on exact main SHA: workflow `tests`, event `push`, run
  `42679687766`, head `d51f8341…`, conclusion **success**
- PR commits `5159878…` and `42e6024…` are reachable from `main`; the deployment
  documentation is present on `main`.

**Branch cleanup results**

- Local `main` fast-forwarded to `d51f8341…`; matches `origin/main`.
- Local `docs/record-url-dump-deploy` deleted safely after ancestor verification
  (`git branch -d`, was `42e6024`).
- Remote `docs/record-url-dump-deploy` deleted by GitHub on merge; confirmed
  absent and pruned.
- Unrelated branches preserved: `docs/unified-ref-consolidation-plan`,
  `fix/youtube-auto-show-notes-api`.
- Working tree clean.

**Task status**

- Task `3c9a71d4` (`ref --url-dump DOMAIN`): **DONE / MERGED / DEPLOYED**;
  record at `.codex/tasks/3c9a71d4-url-dump-domain.md`. PR #28 closure recorded.

**Remaining blockers**

- None for this merge/cleanup.
- Any future production change, including rollback per `ROLLBACK.md`, requires
  separate authorization. The pre-existing `--url-dump` behavior limits are
  unchanged and still documented in the task record.

**Production confirmation**

No package deployment, pipx upgrade, ref-api virtualenv change,
`ref-api.service` restart, Minion configuration change, or production data
modification occurred. This work changed only repository documentation and local
Git metadata.
