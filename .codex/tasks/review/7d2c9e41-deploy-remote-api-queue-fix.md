# [ops] Deploy merged ref fixes and repair transcription producer

- **Task ID:** `7d2c9e41`
- **Owner:** OpenCode
- **State:** REVIEW
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/review/`.
- **Branch:** `ops/deploy-remote-api-queue-fix`
- **Base:** `origin/main` = `ce73299760787abfd4e69b29c51c450cae0ab9d0`
- **Authorization:** Drae authorized production deployment, backed-up producer
  configuration correction, required package upgrades, controlled ref-api
  restart, and one bounded enqueue/transcription canary. No application code
  changes, no bulk replay, no archive rewrite, no worker relocation.

## Authorized sources

- `draeician/ref` = `ce73299760787abfd4e69b29c51c450cae0ab9d0`
- `draeician/local_transcribe` = `b3cf22ee5da337fab9dcd37fb97506f5beab012b`

## Claim

```
[CLAIM] 7d2c9e41 deploy merged ref + repair queue producer
repo: draeician/ref@ops/deploy-remote-api-queue-fix
actor: OpenCode  role: Deployer
task-file: .codex/tasks/wip/7d2c9e41-deploy-remote-api-queue-fix.md
plan:
- Read-only preflight: executables, venvs, service, queue identity, worker, backlog
- Back up configs, service venv, archive/pending metadata; verify rollback
- Deploy ref@ce73299 to the dedicated ref-services venv (minion-26)
- Deploy ref@ce73299 to pipx ref-cli (nomnom) if reachable
- Back up and correct local-transcribe config; upgrade lt to b3cf22e
- One bounded canary; audit backlog without bulk replay
- Record evidence; docs-only PR; leave task in REVIEW
```

## Preflight findings (minion-26, 2026-11-09)

- Host: `minion-26` (Ubuntu 26.04.1 LTS), user `draeician`.
- `ref` on PATH -> `/home/draeician/.local/share/ref-services/ref-api/bin/ref`
  (dedicated service venv, Python 3.13.17), version
  `1.6.12b1.dev129+g80c6e3791`, installed from a wheel under
  `~/.local/share/ref-services/deploy-backups/20261102T1416Z-pr26-url-dump/`.
- `ref-api` on PATH -> `/home/draeician/.local/share/pipx/venvs/ref-cli/bin/ref-api`
  (pipx, version `1.6.12b1.dev144+g377dc3416`) **but the service does not use it**.
- Running `ref-api.service` ExecStart:
  `/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000`,
  `Type=simple`, `Restart=on-failure`, `RestartSec=5`, enabled, active since
  2026-11-07 17:31:45 UTC.
- `/health` -> `{"status":"ok","version":"1.6.12b1.dev129+g80c6e3791"}`.
- `lt` -> pipx `local-transcribe` venv (Python 3.14.4), version `0.7.0`.
- Queue: `/opt/md2/music/youtube/transcripts/transcription-queue` on NFS4
  (`depot.draeician.com:/mnt/tank/md2`, 99% used, 1.1T free).
- `queue.id` UUID `8c6fc098-8cbe-41ae-9689-dd759797a582` (matches
  `REF_LOCAL_TRANSCRIBE_QUEUE_UUID` and `ref-api.env`).
- Stale producer config `~/.config/local-transcribe/config.yaml`:
  `queue.path: /tmp/lt-smoke-queue-59553`,
  `expected_uuid: 6a058908-116f-41c9-987f-d5f4ef38667e`,
  `expected_nfs_version: 3` (to preserve).
- Worker host: `aether` (`worker/state.json` `worker_id aether-910154`); SSH
  reachable; `local-transcribe-worker.service` active/running; its config already
  points at the correct queue/UUID with NFS guards. Worker `lt` is also 0.7.0.
- Queue counts: completed 5607, failed 204, cancelled 670, pending 0, retry 0,
  processing 1 (a stale zero-byte `.tmp` from 2026-10-15), keys 8290.
- Archive: `/home/draeician/references` -> `.../ref-services/staging-references`;
  `references.md` 15,348,296 bytes, sha256
  `b3fc9be906f0eed6318ddbeb4debe6eaf5bc76d2af83d514b59e1f96e7fe8dd6`.
- `transcript-pending.md` is **absent** at both the archive path and
  `staging-references`.
- ref-api logs show `Transcript reconciliation: candidates=20 updated=0
  skipped=20 errors=0`.

## Blocker: nomnom access

- `nomnom` resolves (Tailscale `100.69.237.110`) and is online, but SSH from
  minion-26 and from aether fails with `Permission denied (publickey,password)`.
- No usable private key exists on minion-26 for nomnom; Tailscale SSH host keys
  are not advertised for nomnom. This blocks the mandated nomnom pipx upgrade
  and status/routing smoke test.
- Do not improvise access or modify nomnom host configuration. Record as a
  blocker and proceed with the minion-26 producer repair only.

## Deployment record (2026-11-09/10 UTC)

### Source verification

- ref authorized `ce73299760787abfd4e69b29c51c450cae0ab9d0`; local `main`
  matched and `origin/main` matched before branching.
- local_transcribe authorized `b3cf22ee5da337fab9dcd37fb97506f5beab012b`;
  both local checkouts were clean and at that commit.

### Backups and rollback artifact

Backup dir (mode 700):
`/home/draeician/.local/share/ref-services/deploy-backups/20261109T234313Z-deploy-remote-api-queue-fix`

Captured and verified readable:

- `local-transcribe.config.yaml.before` (sha recorded via copy)
- `ref.config.yaml.before`, `ref-api.env.before`
- `ref-api.service.unit.before`
- `local-transcribe.pipx_metadata.json.before`, `ref-cli.pipx_metadata.json.before`
- `references.md.before` (15,348,296 bytes; sha256
  `b3fc9be906f0eed6318ddbeb4debe6eaf5bc76d2af83d514b59e1f96e7fe8dd6`)
- `queue.id.before` (sha256 `28998c9e2a2181badcb5d30436aa4829141b931aefe32b4e3a416c83eaa4c5ea`)
- `queue-counts.before.txt`
- `service-distributions.txt` (48 dists incl. fastapi 0.161.0, uvicorn 0.54.0,
  starlette 1.9.0), `lt-distributions.txt`
- `rollback-wheel.sha256`: dev129 wheel
  `03ee26870ab8c88de129c01d020d6380ebc3bf682778f9c9d8685f462f0fd7da`
  (verified as a readable zip with 41 files)
- `ref_cli-deployed.whl` sha256
  `49e5c0961172bf7f98a466f4a8d9b67c93e3834635947fb55a799dff47a36e9e`

Rollback:

- ref: restore the dev129 wheel:
  `uv pip install --python /home/draeician/.local/share/ref-services/ref-api/bin/python --no-deps /home/draeician/.local/share/ref-services/deploy-backups/20261102T1416Z-pr26-url-dump/new-wheel/ref_cli-1.6.12b1.dev129+g80c6e3791-py3-none-any.whl`
  then `systemctl --user restart ref-api.service`.
- lt: `pipx install --force --python /usr/bin/python3.14 'git+https://github.com/draeician/local_transcribe.git@25b89f1326751a3b0781051331822c50ffde3b19'`
- config: copy `local-transcribe.config.yaml.before` back with mode/owner preserved.

### Phase 3 — ref deploy (minion-26)

- Built wheel from `ce73299`:
  `ref_cli-1.6.12b1.dev157+gce7329976-py3-none-any.whl`.
- Dependency diff dev129 -> ce73299: **none** (`pyproject.toml`/`setup.cfg`).
- Installed into the dedicated service venv with `uv pip install --no-deps`,
  preserving Python 3.13.17 and the existing 48-dist `[api]` set.
- `ref-api.service` restarted once. `MainPID 895374`, `ActiveState=active`,
  `NRestarts=0`, `ExecStartPre` mount check passed.
- `/health` -> `{"status":"ok","version":"1.6.12b1.dev157+gce7329976"}`.
- Startup log: reconciliation started (interval 300s), `candidates=20
  updated=0 skipped=20 errors=0`; no traceback/error lines after restart.
- `ref --status` on minion-26: `Mode: remote`, `api_url:
  http://127.0.0.1:8000`, `Status: ok (...)`, exit 0.

### Phase 4 — producer repair (minion-26)

- Revalidated `queue.id` UUID `8c6fc098-8cbe-41ae-9689-dd759797a582`, path
  exists, NFS source `depot.draeician.com:/mnt/tank/md2`.
- Backed up and corrected `~/.config/local-transcribe/config.yaml`:
  - `queue.path` -> `/opt/md2/music/youtube/transcripts/transcription-queue`
  - `queue.expected_uuid` -> `8c6fc098-8cbe-41ae-9689-dd759797a582`
  - preserved `expected_nfs_version: 3` and file mode/owner.
- Upgraded `lt` with
  `pipx install --force --python /usr/bin/python3.14 'git+https://github.com/draeician/local_transcribe.git@b3cf22ee5da337fab9dcd37fb97506f5beab012b'`.
  Result: `local-transcribe 0.8.1`, installed using Python 3.14.4 (same base
  interpreter), pipx spec pinned to `b3cf22e`.
- `lt queue path`/`list` now emit **no Deno warning**; queue UUID resolves to
  `8c6fc098-8cbe-41ae-9689-dd759797a582`.
- Queue records unchanged: pending=0, processing=1 (pre-existing stale 0-byte
  `.tmp`), completed=5607, failed=204, retry=0, cancelled=670, keys=8290,
  worker=3; `queue.id` hash unchanged.

### Worker validation (aether)

- `local-transcribe-worker.service` active/running (`lt worker run --standby`).
- Worker config already correct (path, UUID, NFS guards).
- `findmnt`: `/opt/md2` is **NFS vers=3**; `rpc.statd` running.
- `lt queue doctor` on aether: all checks ok (`nfs_version ok (v3)`,
  `rpc_statd ok`), `! NLM lock currently held by another worker` (expected while
  the worker runs).

### STOP condition encountered on minion-26

- minion-26 mounts `/opt/md2` as **NFSv4.2**, while the preserved producer config
  guard is `expected_nfs_version: 3` (a worker NLM guard).
- `lt queue path`/`doctor` on minion-26 therefore report
  `NFS version mismatch ... found 4, expected 3 (SPEC requires NFSv3 for NLM)`.
- The producer enqueue path (`resolve_queue_dir` + `QueueStore.enqueue`) does not
  consult mount validation or NLM; the worker host (aether) is NFSv3 with a valid
  NLM lock. The mismatch is a producer-host guard artifact, not a broken mount.
- Per the task's explicit STOP rule ("STOP if the queue still has an identity or
  mount problem. Do not force an enqueue."), **the canary was NOT submitted** and
  `expected_nfs_version` was **not** changed. No queue job, archive row, or
  pending file was written.
- Decision required: either reaffirm that the producer-only host may carry the
  worker NFSv3 guard (and authorize the canary), or authorize a host-appropriate
  guard/remount change.

### Blocker — nomnom

- `nomnom` is online in Tailscale but SSH from minion-26 and aether returns
  `Permission denied (publickey,password)`; no usable private key and no
  Tailscale SSH server key. The pipx ref-cli upgrade, `--version`/`--status`,
  and HTTP-routing smoke on nomnom were **not** performed.

### Phase 6 — backlog audit (read-only)

- Live `transcript-pending.md` is **absent** on minion-26.
- Archive placeholder classes:
  - 8,811 `queued in transcript-pending.md` (all unique video IDs; pending file
    lost, not replayable from the archive alone)
  - 19 `queued for local-transcribe worker; execution <uuid>`
  - 1 `already in transcription queue: execution <uuid>`
  - 14 `queue has a failed/cancelled job for this source ...`
  - 2 `local-transcribe not installed; recorded in transcript-pending.md`
  - 0 `...; not queued` rows
- The 20 reconciliation candidates all reference **failed** queue executions;
  the reconciler correctly leaves them unchanged (`updated=0 skipped=20`).
- 37 rows end in `|None` (mostly private/unavailable videos); these are the only
  rows `update_transcript()` selects.
- Isolated fixture confirmed the selection predicate: only a `|None` row is
  selectable; `not queued`, worker-placeholder, and historical pending rows are
  not.
- Conclusion: there is **no safe bulk replay** with current supported operations.
  A follow-up coding task is required for a deduplicated, identity-checked
  re-enqueue/recovery command. No production archive rows were modified and no
  pending URLs were replayed.

### Not performed (authorization/safety)

- No canary enqueue/transcription (STOP rule above).
- No nomnom change (access blocker).
- No queue.id change, queue purge, job deletion/rewrite, bulk replay, worker
  install/relocation, or archive rewrite.
