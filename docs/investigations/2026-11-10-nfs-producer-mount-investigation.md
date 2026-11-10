# NFS producer mount investigation (minion-26 vs aether)

- **Date:** 2026-11-10 (UTC)
- **Task:** 7d2c9e41 — deployment/queue-producer investigation
- **Status:** Investigation complete; implementation **not** performed
- **Report owner:** Pi (documentation only)
- **Related task record:** `.codex/tasks/review/7d2c9e41-deploy-remote-api-queue-fix.md`
- **Scope:** Read-only NFS/mount and local-transcribe queue analysis. No host,
  mount, service, repository, or queue change is described as executed here.

## Evidence labels

- **OBSERVED** — captured from the live hosts / repository during the
  investigation.
- **ASSUMED** — an inference from observed facts; not directly tested.
- **PROPOSED** — a recommended change or procedure; **not executed**.

No credentials or secrets are included. Internal hostnames, export paths, and
non-secret queue settings are shown for operational reproducibility.

---

## 1. Summary

- minion-26 (authoritative `ref-api` + queue producer) mounts the shared queue
  export over **NFSv4.2** at `/opt/md2`.
- aether (the local-transcribe worker) mounts the same export over **NFSv3** at
  `/opt/md2` and holds the NLM worker lock.
- Both hosts resolve the same queue directory and the same queue UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582`.
- The producer config preserves `queue.expected_nfs_version: 3` (a worker/NLM
  guard). On minion-26 this makes `lt queue path` / `lt queue doctor` report an
  NFS version mismatch (`found 4, expected 3`).
- The producer enqueue path does **not** perform mount/NLM validation, so this
  is a diagnostic/guard mismatch rather than a broken mount. The worker host is
  correctly NFSv3 with `rpc.statd` and a held NLM lock.
- The recommended remediation is a dedicated **NFSv3 producer mount** of the same
  export, with the producer queue path pointed at that mount and the NFSv3 guard
  preserved. This is **proposed**, not executed.

---

## 2. Hosts and roles

| Host | Role | Evidence |
| --- | --- | --- |
| `minion-26` | Authoritative `ref-api` service and queue producer | `ref-api.service` active; `/health` OK |
| `aether` | local-transcribe worker | `local-transcribe-worker.service` active; holds NLM lock |
| `nomnom` | remote `ref` CLI | Not reachable for this investigation (see §14) |

`minion-26` runs Ubuntu 26.04.1 LTS as user `draeician`.

---

## 3. Exact mounts (OBSERVED)

### minion-26

Command:

```bash
findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue \
  -o TARGET,SOURCE,FSTYPE,OPTIONS -n
mount | grep -E ' /opt/md2 | /opt/md2/'
```

Output:

```text
TARGET   SOURCE                            FSTYPE OPTIONS
/opt/md2 systemd-1                         autofs rw,relatime,fd=82,pgrp=1,timeout=0,minproto=5,maxproto=5,direct,pipe_ino=15653
/opt/md2 depot.draeician.com:/mnt/tank/md2 nfs4   rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,fatal_neterrors=none,proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=192.168.22.54,local_lock=none,addr=192.168.22.17,_netdev,x-systemd.automount
```

```text
systemd-1 on /opt/md2 type autofs (rw,relatime,fd=82,pgrp=1,timeout=0,minproto=5,maxproto=5,direct,pipe_ino=15653)
depot.draeician.com:/mnt/tank/md2 on /opt/md2 type nfs4 (rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,fatal_neterrors=none,proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=192.168.22.54,local_lock=none,addr=192.168.22.17,_netdev,x-systemd.automount)
```

### aether

Command (read-only over SSH):

```bash
ssh aether 'findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue \
  -o TARGET,SOURCE,FSTYPE,OPTIONS -n'
```

Output:

```text
/opt/md2 systemd-1                         autofs rw,relatime,fd=73,pgrp=1,timeout=60,minproto=5,maxproto=5,direct,pipe_ino=13414
/opt/md2 depot.draeician.com:/mnt/tank/md2 nfs    rw,noatime,vers=3,rsize=1048576,wsize=1048576,namlen=255,hard,fatal_neterrors=none,proto=tcp,timeo=600,retrans=2,sec=sys,mountaddr=192.168.22.17,mountvers=3,mountport=44631,mountproto=udp,local_lock=none,addr=192.168.22.17
```

The autofs prefixes differ only in tuning: minion-26 `timeout=0`,
aether `timeout=60`.

---

## 4. Export, protocol versions, and mount options (OBSERVED)

| Item | minion-26 (producer) | aether (worker) |
| --- | --- | --- |
| Export | `depot.draeician.com:/mnt/tank/md2` | `depot.draeician.com:/mnt/tank/md2` |
| Mountpoint | `/opt/md2` | `/opt/md2` |
| FSTYPE | `nfs4` | `nfs` |
| Protocol | `vers=4.2` | `vers=3` |
| Mount protocol | n/a (v4) | `mountvers=3`, `mountport=44631`, `mountproto=udp` |
| Transport | `proto=tcp` | `proto=tcp` |
| Hard/soft | `hard` | `hard` |
| `local_lock` | `none` | `none` |
| `rsize` / `wsize` | 1048576 | 1048576 |
| `rpc.statd` | present | present (`/usr/sbin/rpc.statd`, PID 2914) |
| Queue path | `/opt/md2/music/youtube/transcripts/transcription-queue` | same |
| Queue UUID | `8c6fc098-8cbe-41ae-9689-dd759797a582` | same |

Disk: `/opt/md2` is `79T` total, `78T` used, `1.1T` available, **99% used**.

---

## 5. Queue UUID verification (OBSERVED)

Commands:

```bash
Q=/opt/md2/music/youtube/transcripts/transcription-queue
cat "$Q/queue.id"
sha256sum "$Q/queue.id"
findmnt -T "$Q" -o FSTYPE,SOURCE -n
```

Output:

```text
{
  "queue_uuid": "8c6fc098-8cbe-41ae-9689-dd759797a582",
  "created_at": "2026-07-30T20:54:34-05:00",
  "created_by": "nomnom"
}
28998c9e2a2181badcb5d30436aa4829141b931aefe32b4e3a416c83eaa4c5ea  .../transcription-queue/queue.id
nfs4   depot.draeician.com:/mnt/tank/md2
```

- Queue UUID: **`8c6fc098-8cbe-41ae-9689-dd759797a582`**.
- Earlier stale producer config (now corrected on minion-26) had
  `queue.path: /tmp/lt-smoke-queue-59553` and
  `expected_uuid: 6a058908-116f-41c9-987f-d5f4ef38667e`; those do **not** match
  the live queue.
- `REF_LOCAL_TRANSCRIBE_QUEUE_DIR` and `REF_LOCAL_TRANSCRIBE_QUEUE_UUID` in
  `~/.config/ref/ref-api.env` already point at the correct path/UUID.

Current producer config on minion-26:

```yaml
queue:
  path: /opt/md2/music/youtube/transcripts/transcription-queue
  expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
  expected_nfs_version: 3
```

Worker config on aether:

```yaml
queue:
  path: /opt/md2/music/youtube/transcripts/transcription-queue
  expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
  expected_nfs_version: 3
  expected_server: depot.draeician.com
  expected_export: /mnt/tank/md2
  watch_legacy_pending: false
```

---

## 6. Worker NLM ownership evidence (OBSERVED)

Commands (read-only):

```bash
ssh aether 'systemctl --user list-units --type=service --all | grep -Ei "transcri|worker"'
ssh aether 'pgrep -af "lt worker|local.transcribe"'
ssh aether 'pgrep -a rpc.statd'
ssh aether 'findmnt -T /opt/md2 -o FSTYPE,OPTIONS -n'
ssh aether 'lt queue doctor --queue-dir /opt/md2/music/youtube/transcripts/transcription-queue'
```

Outputs:

```text
local-transcribe-worker.service   loaded active running Local Transcribe Background Worker
910154 /home/draeician/.local/share/pipx/venvs/local-transcribe/bin/python /home/draeician/.local/bin/lt worker run --standby
2914 /usr/sbin/rpc.statd
nfs ... vers=3 ... local_lock=none ...
```

aether `lt queue doctor`:

```text
✓ Queue resolves: /opt/md2/music/youtube/transcripts/transcription-queue
  probe: ok
  fstype: nfs
  source: depot.draeician.com:/mnt/tank/md2
  target: /opt/md2
  nfs: ok
  nfs_version: ok (v3)
  option_soft: ok
  option_nolock: ok
  option_softerr: ok
  local_lock: ok
  hard: ok
  proto: ok (tcp)
  rw: ok
  server: ok
  export: ok
  rpc_statd: ok
! NLM lock currently held by another worker
```

Queue worker metadata (`processing`/`worker`):

```text
worker/worker.lock:
{
  "hostname": "aether",
  "pid": 910154,
  "acquired_at": "2026-11-06T09:16:37.235508+00:00"
}

worker/state.json:
{
  "worker_id": "aether-910154",
  "hostname": "aether",
  "pid": 910154,
  "queue_uuid": "8c6fc098-8cbe-41ae-9689-dd759797a582",
  "started_at": "2026-11-06T09:16:37+00:00",
  "heartbeat_at": "2026-11-07T17:50:25+00:00",
  "current_execution_id": "1919c680-bd13-4ba9-a39a-90a776d20730",
  "active": true
}
```

- Worker process 910154 owns the NLM lock on aether, and the lock record names
  `aether`.
- **Unknown:** `worker/state.json` heartbeat was stale (`2026-11-07`) while the
  service was active. Cause not established; the NLM lock was held. See §14.

---

## 7. Producer path behavior (OBSERVED via source inspection)

Read-only inspection of the authorized `local_transcribe` revision
`b3cf22ee5da337fab9dcd37fb97506f5beab012b`:

- `QueueStore.enqueue()` (producer) does **not** call `validate_queue_mount()`.
- `resolve_queue_dir()` verifies only directory existence and `queue.id` UUID
  (via `verify_queue_identity`); it does **not** validate NFS version or NLM.
- `QueueStore.enqueue()` docstring: *“Concurrent producers use
  publish-pending-first via `link()`, then claim the reservation. Losers cancel
  orphan pendings.”*
- Mount/NLM validation is invoked by `lt queue path`, `lt queue doctor`,
  `cli_worker`, and `services/worker.py` (worker startup, with
  `require_statd=True`).
- `mount_validation.py` treats a version mismatch as `result.ok = False` with:
  `NFS version mismatch for <path>: found <n>, expected <m> (SPEC requires NFSv3
  for NLM).`

minion-26 `lt queue doctor` (OBSERVED):

```text
✓ Queue resolves: /opt/md2/music/youtube/transcripts/transcription-queue
  probe: ok
  fstype: nfs4
  source: depot.draeician.com:/mnt/tank/md2
  target: /opt/md2
  nfs: ok
  nfs_version: fail (got 4)
  option_nolock: ok
  option_softerr: ok
  option_soft: ok
  local_lock: ok
  hard: ok
  proto: ok (tcp)
  rw: ok
  rpc_statd: ok
✗ NFS version mismatch for ...: found 4, expected 3 (SPEC requires NFSv3 for NLM).
! NLM lock currently held by another worker
```

This confirms the mismatch is a guard/diagnostic on the producer host, not a
producer enqueue failure and not a worker failure.

---

## 8. Feasibility of a dedicated NFSv3 producer mount

- **Server capability — OBSERVED:** aether already mounts the identical export
  over NFSv3 (`vers=3`, `mountvers=3`, `mountport=44631`). The server exports
  `/mnt/tank/md2` over v3 today.
- **Client-side mount on minion-26 — NOT EXECUTED.** No v3 mount was created or
  tested. Mounting requires root/sudo and is a host configuration change.
- **ASSUMED:** a second mountpoint of the same export using NFSv3 is possible
  alongside the existing v4.2 mount. This is standard NFS client behavior but has
  not been validated on this host.
- **ASSUMED:** a v3 mount of the same export would resolve to the same physical
  queue directory and same `queue.id`. This should be verified read-only after
  any authorized mount before use (see §9).

---

## 9. Would a v3 mount reach the same queue and UUID?

**ASSUMED (not live-tested).** Both hosts mount the same export
`depot.draeician.com:/mnt/tank/md2`; a new v3 mount of that export should expose
the same underlying tree, hence the same queue directory and `queue.id`.

Required read-only confirmation after any authorized mount:

```bash
NEW=/mnt/ref-queue-v3
test -d "$NEW/music/youtube/transcripts/transcription-queue"
cat "$NEW/music/youtube/transcripts/transcription-queue/queue.id"
sha256sum "$NEW/music/youtube/transcripts/transcription-queue/queue.id" \
          /opt/md2/music/youtube/transcripts/transcription-queue/queue.id
stat -c '%d %i %U:%G %a %n' \
  "$NEW"/music/youtube/transcripts/transcription-queue \
  /opt/md2/music/youtube/transcripts/transcription-queue
```

Expected: identical `queue_uuid` and identical `queue.id` sha256
(`28998c9e…`). Do not use the mount until those match.

---

## 10. Atomic queue publication compatibility

**OBSERVED via source inspection; live compatibility not tested.**

- Producer reservation uses publish-pending-first with `link()` and then claims
  the reservation; losers cancel orphan pendings.
- NFSv3 supports `link()`/`rename()`; the queue design is explicitly
  “Durable NFSv3 transcription queue”.
- The producer does not take the NLM lock; the worker does.
- The existing worker already operates on NFSv3 with `rpc.statd` and the NLM lock.

**Conclusion (ASSUMED):** producer atomic publication is compatible with the
existing NFSv3 worker. A live producer-on-v3 canary is still required to prove it
end-to-end.

---

## 11. Recommended implementation (PROPOSED — not executed)

### Preferred: dedicated NFSv3 producer mount

Keep the existing v4.2 `/opt/md2` mount and add a v3 mount of the same export.

Illustrative unit (validate distro/systemd conventions before use):

```ini
# /etc/systemd/system/mnt-ref-queue-v3.mount
[Unit]
Description=Ref transcription queue (NFSv3 producer mount)
After=network-online.target
Wants=network-online.target

[Mount]
What=depot.draeician.com:/mnt/tank/md2
Where=/mnt/ref-queue-v3
Type=nfs
Options=vers=3,mountvers=3,proto=tcp,hard,_netdev,nofail,local_lock=none,rsize=1048576,wsize=1048576
```

Then point producer settings at the v3 view:

- `~/.config/ref/ref-api.env`:
  `REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/mnt/ref-queue-v3/music/youtube/transcripts/transcription-queue`
- `~/.config/local-transcribe/config.yaml`:
  `queue.path: /mnt/ref-queue-v3/music/youtube/transcripts/transcription-queue`
  - keep `queue.expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582`
  - keep `queue.expected_nfs_version: 3`

Also consider documenting the second mount in the host's mount/autofs
configuration and verifying UID/ACL access (§12).

### Alternative: remount `/opt/md2` as v3

Preserves all absolute paths (no env/config edits) but changes the protocol for
all `/opt/md2` consumers on minion-26, including the `~/Downloads` symlink
target. Higher blast radius.

### Not recommended without review

- Setting `expected_nfs_version: 4` or `null` on minion-26 — silences the
  diagnostic but weakens/bypasses the worker NFSv3 guard.
- `soft`, `nolock`, or `local_lock=flock` mount options — rejected by the
  project mount validator as unsafe.
- Binding a new view over the existing v4.2 tree before validating the v3 mount.

---

## 12. Risks and rollback

### Risks (PROPOSED assessment)

- **UID/ACL behavior:** queue entries are owned `4500:500` while the minion-26
  login user is `uid 1000`. Existing v4 access works via current ACL/export
  semantics; NFSv3 `sec=sys` ID/ACL behavior must be re-validated on a new mount.
- **Mount/autofs disruption** for other `/opt/md2` consumers if `/opt/md2` is
  remounted.
- **Path coupling:** a new mountpoint requires consistent changes to
  `ref-api.env` and local-transcribe config; a partial change can split producer
  writes across paths.
- **Duplicate reservations** if old and new paths are concurrently active.
- **Worker contention:** do not start a second worker or bypass the NLM lock.
- **Disk pressure:** `/opt/md2` is 99% used (1.1T free).
- **Worker heartbeat staleness** observed; confirm worker liveness before canary.

### Rollback (PROPOSED)

1. Disable/remove any new `mnt-ref-queue-v3.mount` (or restore the prior
   `/opt/md2` unit); `systemctl daemon-reload`.
2. Restore `~/.config/ref/ref-api.env` and
   `~/.config/local-transcribe/config.yaml` from the verified deployment backup:
   `~/.local/share/ref-services/deploy-backups/20261109T234313Z-deploy-remote-api-queue-fix/`
   (`ref-api.env.before`, `local-transcribe.config.yaml.before`).
3. Re-verify `/opt/md2/.../queue.id` hash `28998c9e…` and UUID
   `8c6fc098-…`.
4. Restart only `ref-api.service` if its environment changed; verify `/health`
   and `ref --status`.
5. Confirm queue counts are unchanged apart from any expected canary job.

---

## 13. Canary acceptance criteria (PROPOSED)

Before submission:

- v3 mount validated: same `queue.id` hash/UUID; producer user can write.
- `lt queue doctor` all-ok on the producer (including `nfs_version`); worker
  aether remains all-ok with the NLM lock.
- Queue counts and `queue.id` hash snapshotted; target URL confirmed not already
  queued/completed.
- Worker confirmed live and ready; exactly one worker.

After submission (exactly one URL):

- Exactly one new execution with a real `execution_id` and correct `source_key`.
- Queue state advances as expected; not a `transcript-pending.md` fallback.
- No Deno warning from the producer.
- Only the authorized worker claims the job; no duplicate execution.
- Terminal state reached; transcript JSON validates and source/metadata match.
- Reference row updates/reconciles as designed; rest of archive unchanged.
- Abort/rollback on unexpected queue growth, duplicate execution, identity
  mismatch, worker safety failure, unexpected writes, or service instability.

---

## 14. Remaining unknowns and blockers

1. **No v3 producer mount was created or tested on minion-26.**
2. **Producer NFS guard mismatch remains** (`expected_nfs_version: 3` vs
   minion-26 v4.2), so `lt queue path`/`doctor` fail the version check.
3. **Canary not executed** — withheld under the deployment STOP rule; no queue,
   archive, or pending-file write occurred.
4. **nomnom inaccessible** — SSH `Permission denied (publickey,password)` from
   minion-26 and aether; pipx ref-cli deployment and routing/status smoke remain
   outstanding.
5. **Pending transcript recovery not implemented** — live
   `transcript-pending.md` is absent; 8,811 historical pending rows, 20
   failed-execution placeholders, 37 `|None` rows; no safe bulk replay with
   current operations.
6. **Worker heartbeat observation unresolved** — queue state heartbeat was stale
   while the worker service was active; NLM lock was held.
7. **Disk headroom** — `/opt/md2` at 99% utilization.
8. **UID/ACL behavior on a v3 mount** is unverified for the producer user.

---

## 15. Tests / checks performed

**Performed (read-only):**

- `findmnt -T <queue>` and `mount | grep` on minion-26 and aether.
- `cat` and `sha256sum` of `queue.id` on minion-26.
- `df -h /opt/md2`.
- `lt queue path` and `lt queue doctor` on minion-26 and aether.
- `pgrep -a rpc.statd`, worker service/process inspection on aether.
- Source inspection of `local_transcribe` b3cf22e (`QueueStore`, `queue_paths`,
  `mount_validation`, `cli_queue`, `queue_api`).

**Not performed:**

- No NFSv3 mount on minion-26.
- No queue enqueue, replay, retry, delete, or rewrite.
- No archive write.
- No service restart, remount, package upgrade, or host configuration change.

---

## Appendix — exact command index

```bash
# Mounts
findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue -o TARGET,SOURCE,FSTYPE,OPTIONS -n
mount | grep -E ' /opt/md2 | /opt/md2/'
ssh aether 'findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue -o TARGET,SOURCE,FSTYPE,OPTIONS -n'

# Queue identity
Q=/opt/md2/music/youtube/transcripts/transcription-queue
cat "$Q/queue.id"
sha256sum "$Q/queue.id"
findmnt -T "$Q" -o FSTYPE,SOURCE -n
df -h /opt/md2

# Producer / worker diagnostics
lt queue path --queue-dir "$Q"
lt queue doctor --queue-dir "$Q"
ssh aether 'lt queue doctor --queue-dir /opt/md2/music/youtube/transcripts/transcription-queue'
ssh aether 'pgrep -a rpc.statd'
ssh aether 'systemctl --user status local-transcribe-worker.service --no-pager'
```
