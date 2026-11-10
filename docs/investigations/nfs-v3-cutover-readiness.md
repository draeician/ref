# NFSv3 producer cutover readiness preflight

- **Date:** 2026-11-10 (UTC)
- **Task:** `19294572` — NFSv3 producer cutover readiness preflight
  (`.codex/tasks/done/19294572-nfs-v3-producer-cutover-preflight.md`, State
  **DONE**)
- **Related deployment task:** `7d2c9e41` (remains in `.codex/tasks/review/`,
  State `REVIEW`; ownership unchanged)
- **Branch:** `ops/nfs-v3-producer-preflight` (merged and deleted)
- **Base:** `origin/main` = `2cf3e9c755004be5a1072e7f38c6cfe613efe0e2`
- **Status:** Historical preflight complete; **no cutover executed**. The
  proposed additional NFSv3 producer mount is **superseded and not authorized**
  (2026-11-10 stabilization closure).
- **Scope:** Live **read-only** verification on `aether` and `minion-26`, plus a
  proposed cutover, rollback, and canary plan. Historical evidence only.

> **Status update — 2026-11-10 stabilization closure: SUPERSEDED / NOT AUTHORIZED.**
>
> The proposed additional NFSv3 producer mount/cutover is cancelled. Keep the
> existing NFSv4.2 producer mount on `minion-26` and the existing NFSv3/NLM
> worker mount on `aether`; do not install `/mnt/ref-queue-v3`; preserve the
> shared queue UUID `8c6fc098-8cbe-41ae-9689-dd759797a582`; do not weaken NFS/NLM
> safety validation. The observations, gate design, rollback, and canary plan
> below are retained as historical evidence only. Cross-protocol producer safety
> remains unproven and requires a separate **read-only** audit. No mount or
> canary is authorized.

## Evidence labels

- **OBSERVED** — captured from the live hosts during this preflight.
- **ASSUMED** — an inference from observations; not directly tested.
- **PROPOSED** — a recommended change or procedure; **not executed**.

No credentials or secrets are included. Non-secret queue paths, UUIDs, and
service settings are shown for reproducibility.

---

## 1. Executive summary and recommendation

### Worker liveness — PASS (with stability caveats)

`aether`'s worker is demonstrably live and processing:

- One worker process, PID `1011088`, matching `worker.lock` and `state.json`.
- `local-transcribe-worker.service` active/running; one service, one lock.
- NFSv3 mount, `rpc.statd` active, NLM lock held.
- Heartbeat advanced `16:24:07 → 16:32:53` and the claimed execution changed
  `104072e0… → fe513590…`; completed count advanced `5710 → 5711`.
- Continuous recent `yt-dlp` job activity through `16:32:53` (and GPU use at
  93% during capture).
- One active processing reservation; all `1,373` pending entries are
  `status=pending` with `worker=null`; no stuck reservations were found.
- The old zero-byte `.tmp` is a **harmless orphan** (its execution completed on
  2026-10-19; hidden dotfile ignored by the worker). **Do not delete it.**

**Caveat (OBSERVED):** the worker crashed at `2026-11-10 14:29:45` with a GPU
illegal memory access (`CUDA failed with error an illegal memory access`), was
restarted by systemd (`NRestarts=14`), and recovered the in-flight job. It has
also logged repeated `TranscriptPublishError: 'transcript' is empty` failures.
Liveness is therefore established, but **stability is not guaranteed**.

### Cutover readiness — GO, conditional (SUPERSEDED — not authorized)

**Historical assessment only.** The 2026-11-10 stabilization closure cancels the
proposed additional NFSv3 producer mount; do not install `/mnt/ref-queue-v3`.

The dedicated NFSv3 producer mount is technically feasible:

- The server exports the same tree and offers NFSv3 (`nfs` v3, `mountd` v3,
  `nlockmgr` v3/v4, `status`).
- The client already mounts another export over NFSv3 and has `rpc.statd`
  active.
- The proposed `/mnt/ref-queue-v3` path is free and does not touch `/opt/md2`
  or the aether worker mount.

**Conditions:** authorized interactive sudo (passwordless sudo is unavailable),
fresh pre-change backups (exact service unit, drop-ins, queue paths, queue
identity, archive hash), a post-mount UID/ACL write validation, review of the
exact mount unit, and validation of the fail-closed startup gate. Rollback must
restore the original `ref-api.service`/drop-ins, remove the v3 gate, reload both
systemd managers, and validate the API against the original `/opt/md2` queue.
NFSv3 ACL compatibility remains unverified until the mount exists.

### Canary readiness — NO-GO at this time

Do **not** submit the canary yet:

1. **Backlog / priority:** `1,373` pending jobs, all `origin=ref`,
   `priority=20` (the same priority the ref producer sets). A new ref-produced
   canary would sort behind all of them; worker throughput observed is roughly
   one job every 1–9 minutes, so the canary would not run in a bounded window.
2. **Worker stability:** recent GPU core-dump and repeated empty-transcript
   failures. A canary should follow a stability observation window.
3. **UID/ACL:** the queue has an NFSv4 ACL (`+` on the directory); the ACL
   tooling is not installed, and NFSv3 ACL mapping/write access is unverified.

A bounded canary needs separate authorization for one of: a temporary
higher-priority producer override, a bounded backlog decision, or a one-off
high-priority `lt queue add` mount validation (which does not test the ref-api
env path).

---

## 2. Hosts, roles, and clocks (OBSERVED)

| Host | Role | Address / notes |
| --- | --- | --- |
| `minion-26` | Authoritative `ref-api` + queue producer | `192.168.22.54`, Ubuntu 26.04.1 LTS |
| `aether` | local-transcribe worker + NLM lock | NFSv3 client of the same export |
| `depot.draeician.com` | NFS server | `192.168.22.17`, exports `/mnt/tank/md2` |

Clocks at capture:

```text
minion-26=2026-11-10T16:41:12Z
aether=2026-11-10T16:41:12Z
```

Both hosts agreed to the second. NFS server-side timestamps appeared several
minutes offset from client time; timestamps inside worker JSON are worker UTC.

---

## 3. Phase 1 — worker liveness on aether

### 3.1 Service, PID, and process command (OBSERVED)

Commands:

```bash
ssh aether 'systemctl --user status local-transcribe-worker.service --no-pager'
ssh aether 'systemctl --user show local-transcribe-worker.service \
  -p MainPID -p ActiveState -p SubState -p UnitFileState -p NRestarts \
  -p ExecMainStartTimestamp -p Result -p ExecMainStatus'
ssh aether 'pgrep -af "/bin/lt worker run"'
```

Output (excerpt):

```text
● local-transcribe-worker.service - Local Transcribe Background Worker
     Loaded: loaded (/home/draeician/.config/systemd/user/local-transcribe-worker.service; enabled)
     Active: active (running) since Tue 2026-11-10 14:29:55 UTC; 2h 1min ago
   Main PID: 1011088 (lt)
     CGroup: /user.slice/user-1000.slice/user@1000.service/app.slice/local-transcribe-worker.service
             └─1011088 /home/draeician/.local/share/pipx/venvs/local-transcribe/bin/python /home/draeician/.local/bin/lt worker run --standby

MainPID=1011088
ActiveState=active
SubState=running
UnitFileState=enabled
NRestarts=14
ExecMainStartTimestamp=Tue 2026-11-10 14:29:55 UTC
Result=success
ExecMainStatus=0
```

The extra `pgrep -fc` count included the SSH shell running `pgrep` itself; the
actual worker process list contains exactly one `lt worker run --standby`.

### 3.2 NFSv3 mount and rpc.statd (OBSERVED)

```bash
ssh aether 'findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue \
  -o TARGET,SOURCE,FSTYPE,OPTIONS -n'
ssh aether 'systemctl is-active rpc-statd; pgrep -a rpc.statd'
```

Output:

```text
/opt/md2 systemd-1                         autofs rw,relatime,fd=73,pgrp=1,timeout=60,minproto=5,maxproto=5,direct,pipe_ino=13414
/opt/md2 depot.draeician.com:/mnt/tank/md2 nfs    rw,noatime,vers=3,rsize=1048576,wsize=1048576,namlen=255,hard,fatal_neterrors=none,proto=tcp,timeo=600,retrans=2,sec=sys,mountaddr=192.168.22.17,mountvers=3,mountport=44631,mountproto=udp,local_lock=none,addr=192.168.22.17
active
2914 /usr/sbin/rpc.statd
```

### 3.3 NLM lock ownership and worker identity (OBSERVED)

```bash
ssh aether 'Q=/opt/md2/music/youtube/transcripts/transcription-queue; \
  cat "$Q/worker/worker.lock"; cat "$Q/worker/state.json"'
ssh aether '/home/draeician/.local/bin/lt queue doctor --queue-dir "$Q"'
```

Output:

```json
{
  "hostname": "aether",
  "pid": 1011088,
  "acquired_at": "2026-11-10T14:29:56.248230+00:00"
}
```

```json
{
  "worker_id": "aether-1011088",
  "hostname": "aether",
  "pid": 1011088,
  "queue_uuid": "8c6fc098-8cbe-41ae-9689-dd759797a582",
  "started_at": "2026-11-10T14:29:56+00:00",
  "heartbeat_at": "2026-11-10T16:32:53+00:00",
  "current_execution_id": "fe513590-eb53-471e-916f-532a131d594a",
  "active": true
}
```

`lt queue doctor` (ANSI stripped):

```text
✓ Queue resolves: /opt/md2/music/youtube/transcripts/transcription-queue
  nfs: ok
  nfs_version: ok (v3)
  local_lock: ok
  hard: ok
  proto: ok (tcp)
  rw: ok
  server: ok
  export: ok
  rpc_statd: ok
! NLM lock currently held by another worker
```

The live PID matches both lock records, the hostname is `aether`, and the NLM
lock is held. The `doctor` message is expected when the worker itself owns the
lock.

### 3.4 Heartbeat versus system time, and advancement (OBSERVED)

| Capture (UTC) | `heartbeat_at` | `current_execution_id` | `completed` | `pending` |
| --- | --- | --- | ---: | ---: |
| 16:24 | `2026-11-10T16:24:07` | `104072e0-0c3c-4bb1-ae32-5ca88b1e181a` | 5710 | 1374 |
| 16:32 | `2026-11-10T16:32:53` | `fe513590-eb53-471e-916f-532a131d594a` | 5711 | 1373 |
| 16:37 | `2026-11-10T16:32:53` | `fe513590…` | 5711 | 1373 |
| 16:41 | `2026-11-10T16:32:53` | `fe513590…` | 5711 | 1373 |

The heartbeat **advanced across observations**, `completed` advanced, and the
claimed execution changed. The heartbeat then stayed fixed while the long
`fe513590…` job continued — expected, because the worker writes
`state.heartbeat_at = utc_now_iso()` when it **claims** a job, not on a separate
timer (`worker.py` lines 312/462–464/489 in the installed 0.7.0 package).

**Interpretation of the old stale value:** the prior `2026-11-07` heartbeat was
recorded by the previous worker process (`910154`), whose last claimed execution
`1919c680…` completed on 2026-11-07. That process was killed in the 2026-11-10
GPU crash. A stale heartbeat on an **idle** worker is expected with this code and
is not, by itself, evidence of a stuck worker. The current worker is fresh and
has advanced its heartbeat.

### 3.5 Recent logs, polling, and execution activity (OBSERVED)

```bash
ssh aether 'journalctl --user -u local-transcribe-worker.service --no-pager -n 60'
```

Recent activity includes repeated `yt-dlp` launches and job transitions, e.g.:

```text
Nov 10 16:19:51 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=pUxCFOHKcxM
Nov 10 16:20:51 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=oJUEgbl9Z-o
Nov 10 16:21:31 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=y7N0fexGuaY
Nov 10 16:22:27 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=cQlPbEbLdYU
Nov 10 16:22:57 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=vok4LIhPrcc
Nov 10 16:24:08 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=4DARTqN9E_Q
Nov 10 16:32:53 Running yt-dlp CLI: ... https://www.youtube.com/watch?v=IkasQkSBiSU
```

The worker polls every 5 s (`poll_interval_seconds = 5.0`) and claims jobs
sequentially. Continuous claims are the strongest liveness evidence.

**Failures observed (not a liveness failure):**

```text
Nov 10 15:36:36 Job 3f1ffe6d-... failed
local_transcribe.services.transcript_publish.TranscriptPublishError: 'transcript' is empty
Nov 10 15:39:08 Job 3f1ffe6d-... failed
... 'transcript' is empty
```

These are worker-side empty-transcription outcomes, recorded as failed jobs; the
worker continued to claim new jobs.

### 3.6 Outstanding processing, reservations, and the stale `.tmp` (OBSERVED)

```bash
Q=/opt/md2/music/youtube/transcripts/transcription-queue
for d in pending processing retry completed failed cancelled; do
  printf '%s=%s\n' "$d" "$(ls "$Q/$d" | wc -l)"
done
ls "$Q/pending"/*.json | xargs grep -h '"status"' | sort | uniq -c
ls "$Q/pending"/*.json | xargs grep -h '"worker"' | sort | uniq -c
```

Output at 16:41 UTC:

```text
pending=1373
processing=1
retry=0
completed=5711
failed=206
cancelled=670
keys=9770

1373   "status": "pending"
1373   "worker": null
```

The single processing record was `fe513590-eb53-471e-916f-532a131d594a` with
`status=processing`, `started_at=2026-11-10T16:32:53`, `worker=null` (the worker
field is not populated during processing in this version; use the processing
file and `state.current_execution_id`).

The stale zero-byte file:

```text
processing/.9e27f869-a59c-4588-9b18-69ef2a7bbf04.json.tmp.nomnom.7428.e36c88ce9216239a
size=0, mtime=2026-10-15T18:31:24Z
```

Its execution exists and is terminal:

```text
completed/9e27f869-a59c-4588-9b18-69ef2a7bbf04.json  (923 bytes, 2026-10-19)
```

It is a hidden dotfile; the worker selects `pending/*.json` (glob does not match
dotfiles), and it is not blocking the current processing reservation. It is a
harmless orphan from an interrupted publication. **Do not delete it during this
cutover**; a separate cleanup can remove it after confirming no owner needs it.

### 3.7 Exactly one active worker (OBSERVED / ASSUMED)

- One `local-transcribe-worker.service` unit, active/running.
- One `lt worker run --standby` process, PID `1011088`.
- One `worker/worker.lock` naming `aether` and the live PID.
- One held NLM lock; `lt queue doctor` from a separate process reports it held.
- No other local worker unit or process was observed.

**ASSUMED:** no second worker exists on a host we did not inspect (e.g.,
`nomnom` is unreachable). The single shared lock and single live lock owner are
consistent with one worker.

### 3.8 Stability finding — GPU crash and restarts (OBSERVED)

```bash
ssh aether 'journalctl --user -u local-transcribe-worker.service \
  --since "2026-11-10 14:20:00" --until "2026-11-10 14:35:00" --no-pager'
```

Excerpt:

```text
Nov 10 14:29:44 lt[910154]: ... Memory Fault Error ...
Nov 10 14:29:44 lt[910154]: terminate called after throwing an instance of 'std::runtime_error'
Nov 10 14:29:44 lt[910154]:   what():  CUDA failed with error an illegal memory access was encountered
Nov 10 14:29:45 systemd[2659]: local-transcribe-worker.service: Main process exited, code=dumped, status=6/ABRT
Nov 10 14:29:45 systemd[2659]: local-transcribe-worker.service: Failed with result 'core-dump'.
Nov 10 14:29:55 systemd[2659]: local-transcribe-worker.service: Scheduled restart job, restart counter is at 14.
Nov 10 14:29:55 systemd[2659]: Started local-transcribe-worker.service.
Nov 10 14:30:01 lt[1011088]: Recovered processing job 26256b4b-... -> retry/
```

Prior core-dump events were also present on 2026-11-05 and 2026-11-06. The
worker currently shows GPU use at 93%, 2.0 GiB current / 10.1 GiB peak memory.
This is a reliability risk for a canary, not a current liveness failure.

### 3.9 Phase 1 verdict

**PASS for liveness** — fresh PID/lock match, current heartbeat and advancement,
active job claims, one worker, one NLM owner, no stuck reservation, harmless
stale `.tmp`.

**Caveat** — repeated GPU core-dumps and empty-transcript failures mean the
worker is live but not demonstrably stable. Observe a stability window before a
canary.

---

## 4. Phase 2 — producer preflight on minion-26

### 4.1 ref-api health and installed version (OBSERVED)

```bash
curl -fsS http://127.0.0.1:8000/health
ref --version
systemctl --user show ref-api.service -p MainPID -p ActiveState -p NRestarts
```

Output:

```json
{"status":"ok","version":"1.6.12b1.dev157+gce7329976"}
```

```text
ref 1.6.12b1.dev157+gce7329976
MainPID=895374
ActiveState=active
NRestarts=0
ExecMainStartTimestamp=Mon 2026-11-09 23:44:03 UTC
```

`ref --status`:

```text
Mode: remote
api_url: http://127.0.0.1:8000 (127.0.0.1:8000)
Status: ok (version 1.6.12b1.dev157+gce7329976)
```

### 4.2 lt 0.8.1 and pipx provenance (OBSERVED)

```bash
lt --version
pipx list --json
cat ~/.local/share/pipx/venvs/local-transcribe/pipx_metadata.json
find ~/.local/share/pipx/venvs/local-transcribe/lib \
  -path '*local_transcribe-*.dist-info/direct_url.json' -exec cat {} \;
```

Output:

```text
local-transcribe version 0.8.1
```

`pipx_metadata.json` main package:

```json
{
  "package": "local-transcribe",
  "package_version": "0.8.1",
  "package_or_build_url": null,
  "pip_args": ["--force-reinstall"]
}
```

Installed VCS provenance (`direct_url.json`):

```json
{"url": "https://github.com/draeician/local_transcribe.git",
 "vcs_info": {"commit_id": "b3cf22ee5da337fab9dcd37fb97506f5beab012b",
              "requested_revision": "b3cf22ee5da337fab9dcd37fb97506f5beab012b",
              "vcs": "git"}}
```

`lt` is a symlink into the pipx venv. The **worker** on aether is still
`local-transcribe 0.7.0`; a producer/worker version split remains.

### 4.3 Queue UUID and `queue.id` hash (OBSERVED)

```bash
Q=/opt/md2/music/youtube/transcripts/transcription-queue
cat "$Q/queue.id"
sha256sum "$Q/queue.id"
```

Output:

```json
{"queue_uuid": "8c6fc098-8cbe-41ae-9689-dd759797a582",
 "created_at": "2026-07-30T20:54:34-05:00",
 "created_by": "nomnom"}
```

```text
28998c9e2a2181badcb5d30436aa4829141b931aefe32b4e3a416c83eaa4c5ea  .../queue.id
```

### 4.4 Current NFSv4.2 mount health (OBSERVED)

```bash
findmnt -T "$Q" -o TARGET,SOURCE,FSTYPE,OPTIONS -n
```

Output (excerpt):

```text
/opt/md2 systemd-1                         autofs rw,relatime,...timeout=0,...
/opt/md2 depot.draeician.com:/mnt/tank/md2 nfs4   rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,fatal_neterrors=none,proto=tcp,timeo=600,retrans=2,sec=sys,clientaddr=192.168.22.54,local_lock=none,addr=192.168.22.17
```

`/etc/fstab`:

```text
media.draeician.com:/mnt/tank/md1 /opt/md1 nfs rw,vers=3,_netdev,nofail,x-systemd.automount 0 0
depot.draeician.com:/mnt/tank/md2 /opt/md2 nfs4 rw,vers=4.2,_netdev,nofail,x-systemd.automount 0 0
```

The v4.2 mount is healthy; the queue resolves and `queue.id` is readable.
`~/references/transcripts` is a symlink to `/opt/md2/music/youtube/transcripts`,
so the archive still uses `/opt/md2` even after the producer queue moves.

### 4.5 NFSv3 service and export availability (OBSERVED)

```bash
rpcinfo -p depot.draeician.com
showmount -e depot.draeician.com
```

Output (excerpt):

```text
program vers proto   port  service
100005    3   udp  44631  mountd
100005    3   tcp  40969  mountd
100024    1   udp  59709  status
100024    1   tcp  50245  status
100003    3   tcp   2049  nfs
100003    4   tcp   2049  nfs
100227    3   tcp   2049  nfs_acl
100021    3   udp  49134  nlockmgr
100021    4   udp  49134  nlockmgr
```

```text
Export list for depot.draeician.com:
/mnt/tank/md1 *
/mnt/tank/md3 *
/mnt/tank/md2 192.168.22.0/24
```

NFSv3 is available for the same export; the client is inside the export ACL.
Minion-26 also has `rpc.statd` active (PID 2675), `nfs-common 1:2.8.5`, and
`mount.nfs` (linux nfs-utils 2.8.5). `/opt/md1` is already mounted over NFSv3,
proving client-side v3 support.

### 4.6 Root/sudo and existing mounts (OBSERVED)

```bash
id
sudo -n -l
ls -la /mnt
```

Output:

```text
uid=1000(draeician) gid=1000(draeician) groups=...,27(sudo),...
sudo: interactive authentication is required
drwxr-xr-x 4 root root 4096 /mnt
```

- User `draeician` is in the `sudo` group, but **passwordless sudo is not
  configured**. Installing/starting a system mount unit and creating
  `/mnt/ref-queue-v3` require an authorized interactive sudo session.
- Existing mounts: `/opt/md1` (NFSv3), `/opt/md2` (NFSv4.2). No existing
  `/mnt/ref-queue-v3`.
- fstab-generated units include `opt-md1.mount`, `opt-md2.mount`; no
  `mnt-ref\x2dqueue\x2dv3.mount`.

### 4.7 Capacity and inode headroom (OBSERVED)

```bash
df -h /opt/md2
df -i /opt/md2
```

```text
Filesystem                         Size  Used Avail Use% Mounted on
depot.draeician.com:/mnt/tank/md2   79T   78T  1.1T  99% /opt/md2

Filesystem                            Inodes    IUsed      IFree IUse% Mounted on
depot.draeician.com:/mnt/tank/md2 2174731624 23485350 2151246274    2% /opt/md2
```

Space is tight (99%, 1.1T free) but the canary's footprint is small; inode
headroom is ample (2%). The 1,373-job backlog is a larger operational load than
the canary itself.

### 4.8 Proposed `/mnt/ref-queue-v3` path (OBSERVED)

```bash
ls -ld /mnt/ref-queue-v3
findmnt /mnt/ref-queue-v3
```

```text
ls: cannot access '/mnt/ref-queue-v3': No such file or directory
```

The path is free. `/mnt` is root-owned `0755`, so creating the mountpoint and
unit requires sudo. Nothing is installed or written by this preflight.

### 4.9 UID/GID and ACL compatibility (OBSERVED / ASSUMED)

```bash
stat -c 'uid=%u gid=%g %U:%G mode=%a %n' "$Q" "$Q/queue.id" "$Q/pending" "$Q/worker"
ls -ld "$Q"
for p in "$Q" "$Q/pending" "$Q/keys"; do
  printf '%s r=%s w=%s x=%s\n' "$p" \
    "$(test -r "$p" && echo yes || echo no)" \
    "$(test -w "$p" && echo yes || echo no)" \
    "$(test -x "$p" && echo yes || echo no)"
done
```

Output:

```text
uid=4500 gid=500 UNKNOWN:UNKNOWN mode=775 /opt/md2/.../transcription-queue
uid=4500 gid=500 UNKNOWN:UNKNOWN mode=644 /opt/md2/.../queue.id
uid=4500 gid=500 UNKNOWN:UNKNOWN mode=775 /opt/md2/.../pending
uid=4500 gid=500 UNKNOWN:UNKNOWN mode=775 /opt/md2/.../worker

drwxrwxr-x+ 11 4500 500 12 Jul 30 19:45 /opt/md2/.../transcription-queue
```

```text
.../transcription-queue r=yes w=yes x=yes
.../queue.id            r=yes w=yes x=no
.../pending             r=yes w=yes x=yes
.../keys                r=yes w=yes x=yes
```

The `+` shows an NFSv4 ACL granting write access to the local user despite the
`4500:500` ownership. `getfacl`/`nfs4_getfacl`/`getfattr` are **not installed**,
so the ACL cannot be dumped read-only with local tooling.

**ASSUMED / unresolved:** the NFSv3 `sec=sys` view may expose different ACL
mapping. Do not treat the v4 `test -w` result as proof of v3 write access.
Immediately after an authorized v3 mount, re-check ownership and ACLs and perform
a **separately authorized** write probe under the new mount before switching the
producer. This preflight did not write a probe file.

### 4.10 Producer queue-path consumers (OBSERVED)

```
~/.config/ref/ref-api.env:
  REF_LOCAL_TRANSCRIBE_LT=/home/draeician/.local/bin/lt
  REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/opt/md2/music/youtube/transcripts/transcription-queue
  REF_LOCAL_TRANSCRIBE_QUEUE_UUID=8c6fc098-8cbe-41ae-9689-dd759797a582
  REF_YOUTUBE_TRANSCRIPT_MODE=local_only
  REF_TRANSCRIPT_RECONCILE_ENABLED=true

~/.config/local-transcribe/config.yaml:
  queue:
    path: /opt/md2/music/youtube/transcripts/transcription-queue
    expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
    expected_nfs_version: 3
```

The running `ref-api` process (PID 895374) environment contains the same
`REF_LOCAL_TRANSCRIBE_*` values. A broad config scan found no other queue-path
consumer; `crontab` is empty; `~/.config/ref/config.yaml` only sets
`paths.transcripts: ~/references/transcripts`. No producer setting points at
`/mnt/ref-queue-v3` today.

### 4.11 ref-api systemd user service environment (OBSERVED)

```bash
systemctl --user cat ref-api.service
systemctl --user show ref-api.service \
  -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles
```

Effective unit (exact original, captured before any cutover):

```ini
# /home/draeician/.config/systemd/user/ref-api.service
[Unit]
Description=Ref API - URL Archive Service
After=network.target

[Service]
EnvironmentFile=-/home/draeician/.config/ref/ref-api.env
Type=simple
ExecStartPre=/usr/bin/mountpoint -q /opt/md2
ExecStart=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Effective metadata at capture:

```text
FragmentPath=/home/draeician/.config/systemd/user/ref-api.service
DropInPaths=
ExecStart={ path=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api ; argv[]=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000 ; ... }
EnvironmentFiles=/home/draeician/.config/ref/ref-api.env (ignore_errors=yes)
```

- **No drop-ins exist** (`DropInPaths=` is empty; there is no
  `~/.config/systemd/user/ref-api.service.d/` directory). The single unit file
  above is the complete pre-cutover service definition.
- The only `ExecStartPre` is `/usr/bin/mountpoint -q /opt/md2`. Any cutover
  service change must preserve that line and add the new gate; rollback must
  restore exactly this unit and remove the added gate/drop-ins.
- Snapshot this unit, the (absent) drop-in directory, and the `show` output in
  the fresh backup before editing (§5.7).

This is a **user** unit; the new mount is a **system** unit. Cross-manager
ordering cannot be assumed; the fail-closed `ExecStartPre` gate is the reliable
guard. Keep the `/opt/md2` check because the transcripts path still depends on it.

### 4.12 Current producer diagnostics (OBSERVED baseline)

```text
lt queue path --queue-dir "$Q"
  Mount: nfs4 depot.draeician.com:/mnt/tank/md2 -> /opt/md2
  Mount error: NFS version mismatch ... found 4, expected 3
    (SPEC requires NFSv3 for NLM)

lt queue doctor --queue-dir "$Q"
  fstype: nfs4
  nfs_version: fail (got 4)
  ... all other checks ok ...
  ! NLM lock currently held by another worker
```

This is the pre-cutover baseline the v3 mount is intended to fix.

### 4.13 Pending backlog and pending-file state (OBSERVED)

At 16:41 UTC:

```text
pending=1373
processing=1
retry=0
completed=5711
failed=206
cancelled=670
keys=9770
```

Sampled pending records are all:

```json
"origin": "ref", "priority": 20, "status": "pending", "worker": null
```

with `created_at` values today between roughly `13:52` and `15:19` UTC. This is a
large, unexplained ref-origin enqueue that occurred since the 2026-11-09
deployment baseline (which recorded `pending=0`). It was **not** created by this
preflight and must not be replayed or deleted here.

`transcript-pending.md` is now **present** (it was recorded absent on 2026-11-09):

```text
-rw-r--r--+ 1 4500 500 23276 Nov  9 14:52
/opt/md2/music/youtube/transcripts/transcript-pending.md
529 lines
sha256 a7c3c5e30ce44867be89b1e9c09f5db51653f658874a4a8512be9e63f7327bbc
```

The aether worker has `watch_legacy_pending: false`, so this file is not
automatically imported. **Do not modify it** in this cutover.

---

## 5. Phase 3 — cutover design (PROPOSED — not executed)

### 5.1 Mount unit name and content

Generate the filename; do not hand-write it:

```bash
systemd-escape --path --suffix=mount /mnt/ref-queue-v3
# mnt-ref\x2dqueue\x2dv3.mount
```

Verified on minion-26 (systemd 259):

```text
/etc/systemd/system/mnt-ref\x2dqueue\x2dv3.mount
```

Illustrative unit (**not authorized for installation**):

```ini
[Unit]
Description=Ref transcription queue (NFSv3 producer mount)
After=network-online.target
Wants=network-online.target

[Mount]
What=depot.draeician.com:/mnt/tank/md2
Where=/mnt/ref-queue-v3
Type=nfs
Options=vers=3,mountvers=3,proto=tcp,hard,noatime,local_lock=none,rsize=1048576,wsize=1048576,sec=sys

[Install]
WantedBy=multi-user.target
```

Notes:

- `nofail` and `_netdev` are fstab-generator conventions. For this native mount
  unit, use `After=network-online.target` and the fail-closed startup gate in
  §5.4; do not rely on `nofail` to make a missing mount safe.
- Do **not** use `nolock`, `soft`, `local_lock=flock`, or nested mounts.
- `Where=` must exactly match the escaped unit name.

### 5.2 Validation before activation

```bash
sudo systemd-analyze verify '/etc/systemd/system/mnt-ref\x2dqueue\x2dv3.mount'
sudo systemctl daemon-reload
systemctl cat 'mnt-ref\x2dqueue\x2dv3.mount'
```

Do not start or enable until `systemd-analyze verify` passes and the unit has
been reviewed. After an authorized start:

```bash
systemctl is-active 'mnt-ref\x2dqueue\x2dv3.mount'
findmnt -T /mnt/ref-queue-v3 -o TARGET,SOURCE,FSTYPE,OPTIONS -n
```

Expected: `nfs`, `vers=3`, `mountvers=3`, `hard`, `proto=tcp`, source
`depot.draeician.com:/mnt/tank/md2`.

### 5.3 Boot persistence

```bash
sudo systemctl enable 'mnt-ref\x2dqueue\x2dv3.mount'
systemctl is-enabled 'mnt-ref\x2dqueue\x2dv3.mount'
```

Keep the unit in `/etc/systemd/system/` (not `/run`). Do not also add the same
mount to `/etc/fstab`; choose one mechanism to avoid duplicate units.

### 5.4 Reliable fail-closed ref-api startup gate

`ref-api.service` is a systemd **user** unit; the mount is a **system** unit.
Cross-manager ordering cannot be assumed. Keep the existing `/opt/md2` check and
add a **fail-closed gate** that runs as the user and validates the mount
protocol, source, target, queue UUID/hash, and permissions before the API starts.

Do not rely on a bare `mountpoint` check for the v3 mount: it would accept any
filesystem at that path, including a stale local directory or the wrong export.

Install the gate as a user-owned executable:

```bash
install -m 0755 /dev/stdin "$HOME/.local/bin/ref-queue-v3-gate" <<'GATE'
#!/bin/sh
set -eu
export PATH=/usr/local/bin:/usr/bin:/bin

MNT=/mnt/ref-queue-v3
Q="$MNT/music/youtube/transcripts/transcription-queue"
EXPECTED_SOURCE=depot.draeician.com:/mnt/tank/md2
EXPECTED_UUID=8c6fc098-8cbe-41ae-9689-dd759797a582
EXPECTED_HASH=28998c9e2a2181badcb5d30436aa4829141b931aefe32b4e3a416c83eaa4c5ea

# Bounded wait for the system mount unit, then fail closed.
i=0
while [ "$i" -lt 30 ]; do
  /usr/bin/mountpoint -q "$MNT" && break
  i=$((i + 1))
  sleep 2
done
/usr/bin/mountpoint -q "$MNT" || { echo "v3 queue mount not present" >&2; exit 1; }

tgt=$(findmnt -T "$Q" -o TARGET -n)
src=$(findmnt -T "$Q" -o SOURCE -n)
fstype=$(findmnt -T "$Q" -o FSTYPE -n)
opts=$(findmnt -T "$Q" -o OPTIONS -n)

[ "$tgt" = "$MNT" ] || { echo "wrong mount target: $tgt" >&2; exit 1; }
[ "$src" = "$EXPECTED_SOURCE" ] || { echo "wrong source: $src" >&2; exit 1; }
[ "$fstype" = "nfs" ] || { echo "wrong fstype: $fstype" >&2; exit 1; }

# Split the comma-delimited option list into exact tokens. Never use substring
# matching: mountvers=3 must not satisfy vers=3, and mountproto=tcp must not
# satisfy proto=tcp. Each required value must appear exactly once, conflicting
# values are rejected, and unsafe/local-only locking options are refused.
validate_options() {
  printf '%s\n' "$1" | tr ',' '\n' | awk '
    $0 == "vers=3"            { vers++ }
    $0 ~ /^vers=/ &&
      $0 != "vers=3"          { wrong=1 }
    $0 == "mountvers=3"       { mountvers++ }
    $0 ~ /^mountvers=/ &&
      $0 != "mountvers=3"     { wrong=1 }
    $0 == "proto=tcp"         { proto++ }
    $0 ~ /^proto=/ &&
      $0 != "proto=tcp"       { wrong=1 }
    $0 == "hard"              { hard++ }
    $0 == "local_lock=none"   { locnone++ }
    $0 ~ /^local_lock=/ &&
      $0 != "local_lock=none" { wrong=1 }
    $0 == "soft" || $0 == "nolock" { unsafe=1 }
    END {
      if (wrong) {
        print "wrong or conflicting mount option value" > "/dev/stderr"
        exit 1
      }
      if (unsafe) {
        print "unsafe option soft/nolock/local-only locking" > "/dev/stderr"
        exit 1
      }
      if (vers != 1) {
        print "expected exactly one vers=3, found " vers+0 > "/dev/stderr"
        exit 1
      }
      if (mountvers != 1) {
        print "expected exactly one mountvers=3, found " mountvers+0 > "/dev/stderr"
        exit 1
      }
      if (proto != 1) {
        print "expected exactly one proto=tcp, found " proto+0 > "/dev/stderr"
        exit 1
      }
      if (hard != 1) {
        print "expected option hard exactly once, found " hard+0 > "/dev/stderr"
        exit 1
      }
      if (locnone != 1) {
        print "expected exactly one local_lock=none, found " locnone+0 > "/dev/stderr"
        exit 1
      }
    }
  '
}

validate_options "$opts" \
  || { echo "invalid mount options: $opts" >&2; exit 1; }

[ -d "$Q" ] || { echo "queue dir missing" >&2; exit 1; }
[ -r "$Q/queue.id" ] || { echo "queue.id unreadable" >&2; exit 1; }
[ -w "$Q" ] || { echo "queue dir not writable by producer" >&2; exit 1; }
[ -x "$Q" ] || { echo "queue dir not searchable" >&2; exit 1; }

[ "$(sha256sum "$Q/queue.id" | awk '{print $1}')" = "$EXPECTED_HASH" ] \
  || { echo "queue.id hash mismatch" >&2; exit 1; }

python3 - "$Q/queue.id" "$EXPECTED_UUID" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
raise SystemExit(0 if d.get("queue_uuid") == sys.argv[2] else 1)
PY
GATE
```

The gate validates:

- the path is an actual mount at exactly `/mnt/ref-queue-v3`;
- `FSTYPE=nfs`, `SOURCE=depot.draeician.com:/mnt/tank/md2`;
- exact comma-delimited tokens for `vers=3`, `mountvers=3`, `proto=tcp`, `hard`,
  and `local_lock=none`, each present exactly once. Substring matches do not
  count: `mountvers=3` cannot satisfy `vers=3`, and `mountproto=tcp` cannot
  satisfy `proto=tcp`;
- rejection of `soft`, `nolock`, and local-only locking (`local_lock=all`,
  `local_lock=flock`, `local_lock=posix`), even when a required option is also
  present;
- `queue.id` sha256 equals `28998c9e…` and `queue_uuid` equals
  `8c6fc098-8cbe-41ae-9689-dd759797a582`;
- the queue directory is readable, searchable, and writable by the producer
  user. `test -w` is an access check, not a write probe; a real write probe
  remains separately authorized.

Gate acceptance tests before switching the producer:

```bash
# With the v3 mount absent, this must fail.
/home/draeician/.local/bin/ref-queue-v3-gate; echo "exit=$?"   # expect nonzero

# After the authorized mount is up and validated, this must succeed.
/home/draeician/.local/bin/ref-queue-v3-gate; echo "exit=$?"   # expect 0
```

Negative option-parsing tests (must fail) — run before installation:

The harness extracts the installed gate's `validate_options` function and feeds
it synthetic option strings. Only the baseline may succeed; every other case
must be rejected. In particular, `mountproto=tcp` supplies no `proto=tcp` token
and `mountvers=3` supplies no `vers=3` token.

```bash
GATE=$HOME/.local/bin/ref-queue-v3-gate
eval "$(sed -n '/^validate_options()/,/^}/p' "$GATE")"

check() {
  opts=$1; expect=$2
  if validate_options "$opts"; then rc=0; else rc=1; fi
  printf 'exit=%s expected=%s %s\n' "$rc" "$expect" "$opts"
  [ "$rc" -eq "$expect" ] || { echo "UNEXPECTED RESULT" >&2; exit 1; }
}

check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=none' 0
check 'vers=4,mountvers=3,proto=tcp,hard,local_lock=none' 1
check 'vers=3,mountvers=4,proto=tcp,hard,local_lock=none' 1
check 'vers=3,mountvers=3,mountproto=tcp,hard,local_lock=none' 1
check 'vers=3,mountvers=3,proto=udp,hard,local_lock=none' 1
check 'vers=3,mountvers=3,proto=tcp,soft,local_lock=none' 1
check 'vers=3,mountvers=3,proto=tcp,nolock,local_lock=none' 1
check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=all' 1
check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=flock' 1
check 'vers=3,mountvers=3,proto=tcp,hard' 1
check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=none,soft' 1
check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=none,mountvers=4' 1
check 'vers=3,mountvers=3,proto=tcp,hard,local_lock=none,local_lock=all' 1
```

Expected: baseline `exit=0`; every other line `exit=1`. The `mountproto=tcp`
case fails because only exact `proto=tcp` tokens count, and the `vers=4` /
duplicate `mountvers=4` cases fail because `mountvers=3` is not accepted as
`vers=3`.

Do not start `ref-api` unless the gate exits 0. The gate's checks are static
read-only validations; they reject a wrong target/source/protocol, UUID/hash
mismatch, and missing/non-writable queue before systemd launches the API.

The effective service changes (illustrative, not authorized):

```ini
[Service]
ExecStartPre=/usr/bin/mountpoint -q /opt/md2
ExecStartPre=/home/draeician/.local/bin/ref-queue-v3-gate
```

The proposed cutover edits `~/.config/systemd/user/ref-api.service` directly.
If a drop-in is used instead, use a single cutover-owned file named
`~/.config/systemd/user/ref-api.service.d/10-ref-queue-v3.conf`; do not modify
unrelated drop-ins. After changing the user service, reload the **user** manager
and verify the effective unit before restarting the API:

```bash
systemctl --user daemon-reload
systemctl --user cat ref-api.service
systemctl --user show ref-api.service \
  -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles
```

`cat` must show exactly two `ExecStartPre` lines in order: the original
`/usr/bin/mountpoint -q /opt/md2` first, then
`/home/draeician/.local/bin/ref-queue-v3-gate`. `show` must retain the original
`FragmentPath`, `ExecStart`, and `EnvironmentFiles`, and `DropInPaths` must not
contain `10-ref-queue-v3.conf` (it may contain only the original unrelated
drop-ins). Do not restart `ref-api` until the reloaded effective unit is
verified and the gate exits 0.

Both lines run in order; either failure prevents `ref-api` from starting on a
wrong filesystem or wrong queue identity. If the gate script is missing, systemd
fails the start (fail closed). Keep `Restart=on-failure`; a missing/mismatched
mount produces a bounded retry loop rather than silent degradation. Back up the
gate script with the service snapshot, and remove it during rollback if it is no
longer referenced.

### 5.5 Producer configuration changes

Only two files change; both are user-owned:

`~/.config/ref/ref-api.env`:

```text
REF_LOCAL_TRANSCRIBE_QUEUE_DIR=/mnt/ref-queue-v3/music/youtube/transcripts/transcription-queue
```

Keep unchanged:

```text
REF_LOCAL_TRANSCRIBE_LT=/home/draeician/.local/bin/lt
REF_LOCAL_TRANSCRIBE_QUEUE_UUID=8c6fc098-8cbe-41ae-9689-dd759797a582
REF_YOUTUBE_TRANSCRIPT_MODE=local_only
REF_TRANSCRIPT_RECONCILE_ENABLED=true
```

`~/.config/local-transcribe/config.yaml`:

```yaml
queue:
  path: /mnt/ref-queue-v3/music/youtube/transcripts/transcription-queue
  expected_uuid: 8c6fc098-8cbe-41ae-9689-dd759797a582
  expected_nfs_version: 3
```

**Do not change `expected_uuid` or `expected_nfs_version`.** The UUID and NFSv3
guard are the worker contract. `queue.expected_nfs_version: 3` becomes correct
on the new mount and should make `lt queue doctor` pass instead of reporting
`found 4`.

### 5.6 No dependency on `/opt/md2`

- The v3 mount uses `What=depot.draeician.com:/mnt/tank/md2` directly at
  `/mnt/ref-queue-v3`; it is not nested under `/opt/md2` and does not depend on
  the `/opt/md2` mount unit.
- `/opt/md2` remains mounted for the archive (`paths.transcripts`), so
  `ref-api` keeps its existing `/opt/md2` `ExecStartPre` check.
- Do not modify `/opt/md2`, its fstab entry, or the aether worker mount.

### 5.7 Fresh backups immediately before the change

**Do not use the 2026-11-09 backup for config rollback.** Its
`local-transcribe.config.yaml.before` predates the UUID correction and contains
the stale `/tmp/lt-smoke-queue-59553` /
`6a058908-116f-41c9-987f-d5f4ef38667e`.

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BK=$HOME/.local/share/ref-services/deploy-backups/${STAMP}-nfs-v3-cutover
mkdir -p "$BK" && chmod 700 "$BK"

cp -p "$HOME/.config/ref/ref-api.env" "$BK/ref-api.env.before"
cp -p "$HOME/.config/local-transcribe/config.yaml" "$BK/local-transcribe.config.yaml.before"

# Exact service unit + drop-in snapshot + effective view (currently no drop-ins).
cp -p "$HOME/.config/systemd/user/ref-api.service" "$BK/ref-api.service.unit.before"
systemctl --user cat ref-api.service > "$BK/ref-api.service.cat.before"
systemctl --user show ref-api.service \
  -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles \
  > "$BK/ref-api.service.show.before"
if [ -d "$HOME/.config/systemd/user/ref-api.service.d" ]; then
  mkdir -p "$BK/ref-api.service.d.before"
  cp -a "$HOME/.config/systemd/user/ref-api.service.d/." "$BK/ref-api.service.d.before/"
else
  mkdir -p "$BK/ref-api.service.d.before"   # record that none existed
fi
ls -l "$HOME/.local/bin/ref-queue-v3-gate" 2>/dev/null \
  > "$BK/ref-queue-v3-gate.before" || echo "absent" > "$BK/ref-queue-v3-gate.before"

Q=/opt/md2/music/youtube/transcripts/transcription-queue
cp -p "$Q/queue.id" "$BK/queue.id.before"
sha256sum "$Q/queue.id" > "$BK/queue-id.sha256.before"
for d in pending processing retry completed failed cancelled; do
  printf '%s=%s\n' "$d" "$(ls "$Q/$d" | wc -l)"
done > "$BK/queue-counts.before.txt"
printf 'keys=%s\n' "$(find "$Q/keys" -maxdepth 1 -type f | wc -l)" >> "$BK/queue-counts.before.txt"
sha256sum "$HOME/references/references.md" > "$BK/references.md.sha256.before"
stat -c '%s %y %n' "$HOME/references/references.md" > "$BK/references.md.stat.before"
```

The drop-in copy is a **snapshot for evidence and comparison**, not a directory
to restore wholesale. Rollback must not overwrite or delete unrelated drop-ins;
it removes only a cutover-owned `10-ref-queue-v3.conf` if that file was created.

Verify the backup contains the known-good values before proceeding:

```bash
grep -E 'REF_LOCAL_TRANSCRIBE_QUEUE_(DIR|UUID)' "$BK/ref-api.env.before"
grep -A3 '^queue:' "$BK/local-transcribe.config.yaml.before"
test -s "$BK/ref-api.env.before" && test -s "$BK/local-transcribe.config.yaml.before"
grep -E '^ExecStartPre=' "$BK/ref-api.service.cat.before"
grep -E '^DropInPaths=' "$BK/ref-api.service.show.before"
```

Expected:

- queue path `/opt/md2/music/youtube/transcripts/transcription-queue`, UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582`, `expected_nfs_version: 3`;
- exactly one `ExecStartPre=/usr/bin/mountpoint -q /opt/md2`;
- `DropInPaths=` empty;
- gate script marked `absent`.

If the fresh backup does not contain exactly these, **STOP**.

Record `$BK` in the change task before the first mount/config change.

---

## 6. Phase 4 — canary plan (PROPOSED — do not execute yet)

### 6.1 Preconditions (all must be true)

- Fresh backups taken and verified (§5.7), including the exact service unit,
  drop-ins (none), gate-script absence, and queue paths; rollback path recorded.
- Mount installed, validated, enabled, and mounted; `findmnt` shows NFSv3.
- `ref-queue-v3-gate` installed and tested: it rejects a missing mount, wrong
  target/source/protocol, unsafe/local-only locking, wrong UUID/hash, and
  non-writable queue permissions; the §5.4 negative option tests all fail as
  expected.
- Producer `lt queue doctor` is all-ok including `nfs_version: ok (v3)`.
- Post-mount UID/ACL write validation performed under separate authorization.
- Worker liveness freshly re-checked (§3); exactly one worker; no stuck
  processing; heartbeat current/advancing.
- Worker stability window observed with no new core-dump/restart and no
  unexpected failed jobs.
- Backlog/priority decision recorded (see §6.8); do not submit into a 1,373-job
  same-priority backlog and then wait indefinitely.
- Queue counts and archive hash snapshotted immediately before submission.

### 6.2 Unique URL/source selection

Select **one** public, short YouTube video with clear speech that is absent from
all queue states and the archive. Proposed candidate (must be re-verified and
approved at execution time; not enqueued by this preflight):

```text
https://www.youtube.com/watch?v=J---aiyznGQ
```

Read-only uniqueness checks (run immediately before submission):

```bash
Q=/opt/md2/music/youtube/transcripts/transcription-queue
VID=J---aiyznGQ          # replace with the approved candidate
KEY="youtube__${VID}.json"

test ! -e "$Q/keys/$KEY"
! grep -RIl "youtube:${VID}" "$Q"/{pending,processing,retry,completed,failed,cancelled}
! grep -F "youtube:${VID}" "$HOME/references/references.md"
! grep -F "watch?v=${VID}" /opt/md2/music/youtube/transcripts/transcript-pending.md
```

At preflight time these checks were clean for the candidate above. Any match is
a duplicate: choose another URL. Do not use `lt queue add --force`.

### 6.3 Queue counts before/after

Capture before:

```bash
for d in pending processing retry completed failed cancelled; do
  printf '%s=%s\n' "$d" "$(ls "$Q/$d" | wc -l)"
done
printf 'keys=%s\n' "$(find "$Q/keys" -maxdepth 1 -type f | wc -l)"
sha256sum "$Q/queue.id"
sha256sum "$HOME/references/references.md"
```

After submission, expect exactly one new execution/key, then `pending` −1 and
`completed` +1 as the worker claims and finishes. Other deltas are attributable
to the ongoing backlog and must be distinguished; if you cannot distinguish
them, stop and preserve counts.

### 6.4 Expected execution and state transitions

Submit through the real producer path, not directly to the queue:

```bash
ref "https://www.youtube.com/watch?v=${VID}"
```

Capture the response and the new execution ID (the producer returns/records a
new UUID; it is not precomputed). Expected:

```text
pending/<execution_id>.json   origin=ref, priority=20,
                              source_key=youtube:<VID>,
                              status=pending
        ↓ worker claim (processing file, started_at set)
processing/<execution_id>.json status=processing
        ↓ terminal
completed/<execution_id>.json  status=completed, completed_at set,
                              output_path/generation set
```

A `failed/` terminal state is a valid outcome to record, but it is not a
successful canary and triggers the STOP/rollback decision.

### 6.5 Worker claim and terminal result

- Claimed by exactly one worker: the live aether PID, single NLM owner.
- `state.json.current_execution_id` briefly equals the canary execution ID
  (heartbeat advances at claim).
- No second execution for the same `source_key`; no duplicate key.
- Terminal state reached within the agreed window; record timestamps.

### 6.6 Transcript JSON validation

```bash
T="$HOME/references/transcripts/${VID}.json"
python3 -m json.tool "$T" >/dev/null
python3 - "$T" "$VID" <<'PY'
import json, sys
p, vid = sys.argv[1], sys.argv[2]
d = json.load(open(p))
assert d.get("metadata", {}).get("id") == vid, "metadata.id mismatch"
assert isinstance(d.get("transcript"), str) and d["transcript"].strip(), "empty transcript"
print("ok: metadata.id and nonempty transcript")
PY
```

Also confirm source URL/key and generation match the execution record.

### 6.7 Reference reconciliation and no Deno warning

- `references.md` row for the video is updated by `ref-api`; the reconciler runs
  every 300 s (`REF_TRANSCRIPT_RECONCILE_ENABLED=true`). Record the before/after
  row and the journal line `Transcript reconciliation: candidates=...`.
- Only the canary row should change; compare against the pre-canary backup and
  archive hash. Do not rewrite the archive.
- Capture producer output and journal; assert no `Deno` warning:

```bash
lt --version                       # producer: 0.8.1
ref "https://www.youtube.com/watch?v=${VID}" 2>&1 | tee /tmp/canary-ref.log
grep -i deno /tmp/canary-ref.log && echo "DENO WARNING: STOP"
```

### 6.8 STOP and rollback triggers

STOP immediately (do not force, do not delete queue entries) if any of:

- Mount is missing, read-only, not NFSv3, or `/mnt/ref-queue-v3` is not the
  expected export.
- The fail-closed gate can be bypassed or accepts a wrong filesystem/source/
  protocol/UUID/permissions; or the restored unit still references the v3 gate.
- `queue.id` hash/UUID changes; identity mismatch.
- Duplicate key/execution, second worker, duplicate NLM owner, or stuck
  processing.
- Canary not claimed within the agreed window (backlog/priority unresolved).
- Worker restart/core-dump/GPU error, or heartbeat/progress stops.
- Empty transcript (`TranscriptPublishError: 'transcript' is empty`).
- Unexpected queue growth (beyond the canary), writes outside `/mnt/ref-queue-v3`
  and the expected queue paths, archive hash change beyond the canary row, or
  service instability.
- Any Deno warning or producer error.

Rollback per §7; preserve all evidence; do not bulk replay.

### 6.9 Backlog/priority note (blocking)

All `1,373` pending jobs are `origin=ref, priority=20`, exactly what the ref
producer will assign to the canary. The worker selects by descending priority
then `created_at` (`select_next_execution`: `(-j.priority, j.created_at, ...)`),
and `lt queue add` defaults to priority `50` (higher than 20). A ref-produced
canary therefore sorts **behind** the entire backlog.

Options requiring separate authorization:

- A one-off `lt queue add --priority 100 --origin ref` with the v3 queue dir to
  validate mount/publication (does not test the ref-api env path).
- A temporary producer priority override (code/config change, out of scope).
- A bounded backlog/drain decision (not a bulk replay under this task).

Do not submit the canary until one option is approved.

---

## 7. Ordered rollback (PROPOSED)

Use only the fresh backup from §5.7. Never restore the 2026-11-09
`local-transcribe.config.yaml.before`.

The order is deliberate: stop the producer, restore the **service
configuration** and original queue paths, remove the dedicated mount, reload
both systemd managers, then restart and validate the API against the original
queue.

1. **Stop the producer**:
   ```bash
   systemctl --user stop ref-api.service
   systemctl --user is-active ref-api.service || true   # expect inactive/failed
   ```
   Confirm it is stopped before changing the service, paths, or mount.

2. **Restore the exact original user service and remove the cutover-owned
   NFSv3 dependency**:
   ```bash
   cp -p "$BK/ref-api.service.unit.before" "$HOME/.config/systemd/user/ref-api.service"
   # The proposed cutover edits the main unit, so no drop-in is created. If a
   # dedicated drop-in was used instead, remove only that cutover-owned file.
   # Never delete the drop-in directory or unrelated drop-ins.
   rm -f "$HOME/.config/systemd/user/ref-api.service.d/10-ref-queue-v3.conf"
   rm -f "$HOME/.local/bin/ref-queue-v3-gate"
   ```
   The restored unit must contain exactly the original
   `ExecStartPre=/usr/bin/mountpoint -q /opt/md2`; it must **not** contain
   `ref-queue-v3-gate` or any `/mnt/ref-queue-v3` dependency. Leave all unrelated
   drop-ins untouched; do not restore the §5.7 drop-in snapshot over the live
   directory.

3. **Restore the original queue paths**:
   ```bash
   cp -p "$BK/ref-api.env.before" "$HOME/.config/ref/ref-api.env"
   cp -p "$BK/local-transcribe.config.yaml.before" "$HOME/.config/local-transcribe/config.yaml"
   grep -E '^REF_LOCAL_TRANSCRIBE_QUEUE_(DIR|UUID)' "$HOME/.config/ref/ref-api.env"
   grep -A3 '^queue:' "$HOME/.config/local-transcribe/config.yaml"
   ```
   Expected: path `/opt/md2/music/youtube/transcripts/transcription-queue`,
   UUID `8c6fc098-8cbe-41ae-9689-dd759797a582`,
   `expected_nfs_version: 3`.

4. **Remove the dedicated mount safely** (ref-api is already stopped):
   ```bash
   sudo systemctl stop 'mnt-ref\x2dqueue\x2dv3.mount'    # or umount /mnt/ref-queue-v3
   sudo systemctl disable 'mnt-ref\x2dqueue\x2dv3.mount'
   sudo rm -f '/etc/systemd/system/mnt-ref\x2dqueue\x2dv3.mount'
   findmnt /mnt/ref-queue-v3 && echo "STILL MOUNTED: STOP" || echo "unmounted"
   ```
   Do not remove `/opt/md2`, its fstab entry, or the aether worker mount.

5. **Reload both relevant managers** after the service, path, and mount changes:
   ```bash
   systemctl --user daemon-reload
   sudo systemctl daemon-reload
   ```

6. **Verify the reloaded effective unit**:
   ```bash
   systemctl --user cat ref-api.service
   systemctl --user show ref-api.service \
     -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles
   ```
   Verify with `cat` that the only `ExecStartPre` is the original
   `/usr/bin/mountpoint -q /opt/md2` (there is no `ref-queue-v3-gate` line), and
   with `show` that `FragmentPath`/`ExecStart`/`EnvironmentFiles` match
   `$BK/ref-api.service.show.before` and `DropInPaths` contains no
   `10-ref-queue-v3.conf`. If `DropInPaths` was empty before and no unrelated
   drop-ins were added, it must be empty again; otherwise it must contain only
   the unrelated drop-ins.

7. **Verify `/opt/md2` health and identity**:
   ```bash
   Q=/opt/md2/music/youtube/transcripts/transcription-queue
   findmnt -T "$Q" -o TARGET,SOURCE,FSTYPE,OPTIONS -n   # expect nfs4/vers=4.2
   sha256sum "$Q/queue.id"                             # expect 28998c9e…
   cat "$Q/queue.id"                                   # expect 8c6fc098-…
   ```

8. **Verify no v3 references remain**:
   ```bash
   grep -R -- 'ref-queue-v3' "$HOME/.config/ref" "$HOME/.config/local-transcribe" \
     "$HOME/.config/systemd/user" || echo none
   grep -R -- 'lt-smoke-queue-59553\|6a058908-116f-41c9-987f-d5f4ef38667e' \
     "$HOME/.config/ref" "$HOME/.config/local-transcribe" || echo none
   ```
   The stale smoke-test values must appear nowhere.

9. **Restart and validate against the original queue**:
   ```bash
   systemctl --user start ref-api.service
   curl -fsS http://127.0.0.1:8000/health
   ref --status
   tr '\0' '\n' < /proc/$(systemctl --user show -p MainPID --value ref-api.service)/environ \
     | grep -E '^REF_LOCAL_TRANSCRIBE_QUEUE_(DIR|UUID)'
   lt queue path --queue-dir "$Q"
   ```
   Expected: `/health` reports the installed version, `ref --status` is `ok`,
   the running process env points at `/opt/md2/...` with UUID
   `8c6fc098-…`, and `lt queue path` shows the pre-cutover baseline
   (`found 4, expected 3`). That baseline message is expected and is **not** a
   new failure; the canary remains NO-GO.

10. **Archive integrity:** compare `sha256sum ~/references/references.md` and
    its size/mtime with `$BK/references.md.sha256.before`/`.stat.before`. If a
    canary ran, account for exactly the canary row; do not restore an archive
    snapshot over newer writes.

11. **Queue integrity:** confirm counts match the pre-change snapshot except for
    the canary execution; do not delete or rewrite queue entries. Preserve any
    canary evidence for review.

Service stop/start boundaries: stop `ref-api` before any service/path/mount
change; restore the service unit and paths, remove the mount, then reload both
the **user** and **system** managers; verify the effective user unit with `cat`
and `show`; start only after the v3 mount is gone, the original `ExecStartPre` is
verified, and `/opt/md2` identity matches.

---

## 8. Risks and unresolved unknowns

1. **NFSv3 ACL mapping is unverified.** The queue has an NFSv4 ACL; local ACL
   tooling is absent. A v3 `sec=sys` view may not grant the same write access.
   Resolve with a post-mount, separately authorized write probe.
2. **Worker stability:** GPU core-dump at 14:29 today; `NRestarts=14`; repeated
   empty-transcript failures. Worker is live but not proven stable.
3. **Producer/worker version split:** minion `lt` 0.8.1 vs aether worker 0.7.0.
   The canary is the first producer-on-v3 end-to-end proof.
4. **Backlog and priority:** 1,373 same-priority pending jobs; a normal ref
   canary will not run promptly. Requires an authorization decision.
5. **Queue state changed since the deployment record:** pending 0 → 1,373,
   `keys` 8290 → 9770, completed 5607 → 5711, and `transcript-pending.md`
   reappeared (529 lines). Cause not established; must not be replayed/deleted
   here.
6. **Disk pressure:** `/opt/md2` 99% used (1.1T free); inodes 2%.
7. **sudo:** passwordless sudo unavailable; mount installation requires an
   authorized interactive session.
8. **Cross-manager ordering / wrong-path startup:** user `ref-api` vs system
   mount. The fail-closed `ref-queue-v3-gate` validates mount target, source,
   protocol, UUID/hash, and permissions before start; test it after installation.
9. **Server clock skew:** NFS-side mtimes appeared several minutes offset; use
   in-file UTC timestamps for heartbeat/transition reasoning.
10. **Service rollback completeness:** the cutover edits the user unit (adds the
    gate) and creates a gate script. Backups must cover the exact unit, the
    drop-in snapshot (currently none), and gate absence; rollback restores the
    unit, removes only the cutover-owned drop-in/gate, preserves unrelated
    drop-ins, runs `systemctl --user daemon-reload`, and verifies the effective
    unit with `systemctl --user cat`/`show`.
11. **Startup-gate option parsing:** substring checks are unsafe because
    `mountvers=3` contains `vers=3` and `mountproto=tcp` contains `proto=tcp`.
    The gate uses exact comma-delimited tokens, rejects wrong/duplicate values,
    and rejects `soft`, `nolock`, and local-only locking. Run the negative tests
    in §5.4 before installation.

---

## 9. GO / NO-GO

| Decision | Result |
| --- | --- |
| Worker liveness | **GO / PASS** — fresh PID/lock, heartbeat advanced, active claims, one worker, harmless `.tmp`. |
| Mount installation | **SUPERSEDED — not authorized.** The 2026-11-10 stabilization closure cancels the proposed additional NFSv3 producer mount. |
| Canary now | **NO-GO** — 1,373 same-priority backlog, recent GPU crash/restarts, empty-transcript failures, and unverified v3 ACL. |
| Canary after conditions | **NOT AUTHORIZED** — the closure authorizes no canary; any future proposal needs separate authorization. |

**Closure decision:** keep the existing NFSv4.2 producer mount on `minion-26` and
the NFSv3/NLM worker mount on `aether`; do not install `/mnt/ref-queue-v3`; do
not weaken NFS/NLM safety validation; preserve the shared queue UUID
`8c6fc098-8cbe-41ae-9689-dd759797a582`. Cross-protocol producer safety remains
unproven and requires a separate **read-only** audit.

**No canary is authorized by this correction.** The `1,373`-job backlog, recent
GPU instability, and unverified NFSv3 permissions remain unresolved; the NO-GO
stands until a separate authorization and the §6 preconditions are met.

---

## 10. Exact command index

```bash
# Worker liveness (aether)
ssh aether 'systemctl --user status local-transcribe-worker.service --no-pager'
ssh aether 'systemctl --user show local-transcribe-worker.service -p MainPID -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestamp -p Result'
ssh aether 'pgrep -af "/bin/lt worker run"'
ssh aether 'findmnt -T /opt/md2/music/youtube/transcripts/transcription-queue -o TARGET,SOURCE,FSTYPE,OPTIONS -n'
ssh aether 'systemctl is-active rpc-statd; pgrep -a rpc.statd'
ssh aether '/home/draeician/.local/bin/lt queue doctor --queue-dir /opt/md2/music/youtube/transcripts/transcription-queue'
ssh aether 'journalctl --user -u local-transcribe-worker.service --no-pager -n 60'
ssh aether 'cat /opt/md2/music/youtube/transcripts/transcription-queue/worker/worker.lock'
ssh aether 'cat /opt/md2/music/youtube/transcripts/transcription-queue/worker/state.json'
ssh aether 'ls -la /opt/md2/music/youtube/transcripts/transcription-queue/processing'

# Producer preflight (minion-26)
curl -fsS http://127.0.0.1:8000/health
ref --version; ref --status
lt --version
find ~/.local/share/pipx/venvs/local-transcribe/lib -path '*local_transcribe-*.dist-info/direct_url.json' -exec cat {} \;
Q=/opt/md2/music/youtube/transcripts/transcription-queue
cat "$Q/queue.id"; sha256sum "$Q/queue.id"
findmnt -T "$Q" -o TARGET,SOURCE,FSTYPE,OPTIONS -n
rpcinfo -p depot.draeician.com
showmount -e depot.draeician.com
id; sudo -n -l
ls -la /mnt; ls -ld /mnt/ref-queue-v3
df -h /opt/md2; df -i /opt/md2
stat -c 'uid=%u gid=%g %U:%G mode=%a %n' "$Q" "$Q/queue.id"
ls -ld "$Q"
grep -E '^REF_LOCAL_TRANSCRIBE|^REF_YOUTUBE_TRANSCRIPT_MODE' ~/.config/ref/ref-api.env
systemctl --user cat ref-api.service
systemctl --user show ref-api.service -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles
ls -la ~/.config/systemd/user/ref-api.service.d 2>&1
lt queue path --queue-dir "$Q"
lt queue doctor --queue-dir "$Q"

# Service snapshot (before cutover)
cp -p ~/.config/systemd/user/ref-api.service "$BK/ref-api.service.unit.before"
systemctl --user cat ref-api.service > "$BK/ref-api.service.cat.before"
systemctl --user show ref-api.service -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles > "$BK/ref-api.service.show.before"

# Cutover user-service change: edit the unit to add the gate, then reload/verify
systemctl --user daemon-reload
systemctl --user cat ref-api.service
systemctl --user show ref-api.service -p FragmentPath -p DropInPaths -p ExecStart -p EnvironmentFiles
grep -E '^ExecStartPre=' "$BK/ref-api.service.cat.before"
grep -E '^DropInPaths=' "$BK/ref-api.service.show.before"

# Rollback / mount teardown: after restoring the unit/paths and removing the mount
systemctl --user daemon-reload
sudo systemctl daemon-reload
systemctl --user cat ref-api.service
systemctl --user show ref-api.service -p FragmentPath -p DropInPaths -p ExecStart

# Counts and baselines
for d in pending processing retry completed failed cancelled; do printf '%s=%s\n' "$d" "$(ls "$Q/$d" | wc -l)"; done
find "$Q/keys" -maxdepth 1 -type f | wc -l
sha256sum "$HOME/references/references.md"
wc -l /opt/md2/music/youtube/transcripts/transcript-pending.md

# Unit name
systemd-escape --path --suffix=mount /mnt/ref-queue-v3
```

---

## 11. Stabilization closure (2026-11-10)

The proposed additional NFSv3 producer mount is **cancelled, superseded, and not
authorized**. No `/mnt/ref-queue-v3` mount was installed.

- Keep the existing NFSv4.2 producer mount on `minion-26`.
- Keep the existing NFSv3/NLM worker mount on `aether`.
- Preserve the shared queue UUID `8c6fc098-8cbe-41ae-9689-dd759797a582`.
- Do not weaken NFS/NLM safety validation.
- Do not execute the proposed cutover, rollback, or canary procedures in this
  document; they are retained as historical evidence only.
- Cross-protocol producer safety remains unproven and requires a separate
  **read-only** audit. This closure does not claim it has been demonstrated.
