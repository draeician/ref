# Unified ref consolidation and migration plan

Date: 2026-11-06
Status: PROPOSED - planning only; implementation, migration, deployment, and release are not authorized by publication of this document.
Architect/reviewer: ChatGPT
Execution agents: Pi and OpenCode
Authorization and product decisions: Drae
Coordination: root `HANDOVER.md`, with root `HANDOFF.md` retained as the project communication index and historical record.

## 1. Outcome and scope

Consolidate `refwatch` into `draeician/ref`. Make `ref` and `refwatch` clients of one authoritative `ref-api`, rather than independent archive writers. Preserve URL capture, YouTube and Reddit link discovery, transcripts, enrichment, Discord attachments and plain-text capture, search, listing, URL dumps, backups, and maintenance capabilities.

The production archive must be identifiable, configured explicitly, backed up, and shared by every production ingestion path. Where existing archives diverged, reconcile their genuine data without losing references or associated assets. Staging remains a separate, deliberately isolated archive: one production authority does not mean tests should write production data.

Provide GitHub update detection and installation-specific instructions for the running API, CLI, and Discord adapter. Instructions must preserve installation source, Python interpreter, extras, dependencies, and service ownership. Notifications must never upgrade or restart services automatically.

This is complete only after reviewed code is merged, a verified release is available through the chosen installation channel, the intended production installations are upgraded, data reconciliation is verified, end-to-end capture works from Discord and a remote CLI, and obsolete writers are retired. A merged PR alone is not completion.

Non-goals: a new web UI, arbitrary recursive web crawling, a database rewrite, multi-channel Discord expansion, replacing local-transcribe, unrelated refactoring, or changing production during investigation.

## 2. Evidence baseline and limits

Source inspection was performed against these exact revisions:

| Repository | Revision | Role |
| --- | --- | --- |
| `draeician/ref` | `80c6e379106a73c047cd517e56207bc62d558d7f` | CLI, API, archive operations, discovery, current upgrade support |
| `draeician/refwatch` | `6697a9c4c5ce143e21caf027fdb2db40e420e373` | Discord adapter, subprocess integration, images and channel records |
| `draeician/ol` | `e2433f0861b64fb09cb08fcdf1b74e2251e8dc9b` | Reference implementation for cached GitHub version checks |

The November 6 journal excerpt supplied by Drae shows refwatch invoking a `ref` executable inside the ref-api service environment, discovering the OpenCRT GitHub URL from a Reddit post, receiving a formatted reference row and exit code zero, then deleting the Discord message. This is evidence of execution and reported success, not proof of the physical destination or long-term persistence. Do not put the raw production journal in this public repository.

No live host filesystem, running process environment, mount namespace, or archive contents were inspected during this architectural review. No application tests were executed during that source review. The OpenCRT incident's exact cause remains unproven. Both destination divergence and a subsequent conflicting write must be investigated; neither is established by the journal alone.

### Confirmed code findings

| Area | Current behavior | Consequence |
| --- | --- | --- |
| Local archive configuration | `ref_cli.cli` initializes `BASE`, `UNIFIED`, and transcript paths from bundled defaults. `load_config()` returns the user YAML but does not update those globals. Logs also initialize beneath `~/references` at import. | User-configured paths and actual write paths can disagree. Importing client code can have filesystem side effects. [S1] |
| CLI routing | `run_ingest()` uses the API when configured, otherwise processes locally. Ordinary CLI startup creates/migrates local archive state before routing ingest/search; URL dump has an earlier special dispatch. | The API exists, but clients are not cleanly separated from archive ownership. [S2, S3] |
| API storage | API startup bootstraps the CLI module's archive globals; the service calls CLI ingestion functions. | The API is not yet an independently configured storage boundary. [S4] |
| Write locking | The shared archive lock is a process-local `threading.RLock`. Its own documentation excludes independent processes. | Concurrent local CLI/helper writers and the API can bypass each other's locking. This is a real risk, not a proven explanation of this incident. [S5] |
| YouTube links | API-managed durable discovery reads metadata cards/descriptions and queues child ingests. Children do not recursively scan their own YouTube show notes. | Preserve this capability and its bounded/background behavior. [S6] |
| Reddit links | The legacy CLI's Reddit branch discovers outbound URLs and recursively calls `process_url()` directly. | Reddit children do not necessarily pass through API-level skip/discovery/playlist policy. Unify the processing contract. [S7] |
| Playlists | The YouTube show-note worker records discovered playlists without expanding their videos. Direct playlist ingestion expands. `get_youtube_data()` prioritizes a non-radio `list=` parameter over `v=`. | The existing behavior is not uniformly 'ignore playlists unless the playlist is the only target.' A video URL with playlist context can expand a playlist. [S6, S8] |
| Success detection | The API classifies captured stdout; nonempty unrecognized output can become `added`. Refwatch relies on subprocess status and error-text heuristics before deletion. | Merely replacing subprocess invocation with HTTP is insufficient. Persistence outcomes must be structured. [S9, S10] |
| Discord non-URL content | Images are downloaded separately by refwatch; plain-text messages are recorded in local JSONL. | A URL-only port would silently lose or fragment existing capabilities. [S10] |
| Upgrades | `ref` already has pipx metadata inspection and an explicitly invoked upgrade executor, but no ol-style GitHub freshness check. `ol` checks a literal version in GitHub's `pyproject.toml` with a 24-hour cache. Ref uses dynamic setuptools_scm versioning. | Reuse ideas, not an unchanged copy of ol's version lookup or install command. [S11, S12, S13] |
| Packaging | Ref advertises Python >=3.7; refwatch requires >=3.11 and has asynchronous test/lint/type tooling. Ref enumerates packaged modules explicitly. | Resolve the real support floor and package inclusion before merging. Do not silently drop refwatch's gates. [S13, S14] |

The source `HANDOFF.md` contains historical deployment/merge statements that must not be assumed to describe today's installations. Phase 1 reconciles code, installed distributions, loaded service processes, and operator evidence.

## 3. Target architecture

```text
ref CLI ----------- HTTP ----------+
                                  |
refwatch (Discord) - HTTP ---------+--> ref-api --> authoritative archive
                                  |       |
other approved clients -----------+       +--> durable discovery / receipt state
                                          +--> transcripts and enrichment
                                          +--> media and channel records
                                          +--> existing local-transcribe integration
```

Keep `ref-api.service` and `refwatch.service` as independent processes. They may use the same installed distribution; they must not share an event loop or require the CLI subprocess bridge.

Recommended source layout, introduced incrementally rather than through a wholesale move:

```text
src/ref_cli/       terminal presentation and compatibility commands
src/ref_api/       HTTP endpoints, workers, operator status
src/ref_core/      configuration, archive writes, ingestion policy and results
src/ref_client/    side-effect-free HTTP client and response types
src/refwatch/      Discord adapter, delivery state and API calls
```

Existing legacy functions may remain temporarily behind a server-owned adapter. Client packages must not import a module that initializes archive directories or server workers. New modules must be included in built wheels, not only importable from the checkout.

Use one distribution, `ref-cli`, with optional `api` and `discord` dependency groups; preserve the existing `api` extra and entrypoints. A host running both services can install both extras. CLI-only hosts need no Discord dependencies. Verify minimal/base installation behavior rather than assuming an extras declaration isolates imports.

Proposed release: `2.0.0`, because API-required normal operation and an honestly supported Python floor may be breaking changes. Proposed floor: Python 3.11, subject to Phase 1 compatibility evidence and Drae's approval. Record the selected matrix before implementation. Do not tag or change versions for this planning-only branch.

## 4. Storage ownership and diagnostics contract

### 4.1 One production writer

Normal CLI and Discord ingestion require a configured API endpoint. Missing/unreachable configuration produces an actionable error or a retained retryable submission, never a silent local archive fallback. Existing explicit exports/backups may create user-requested local files, but those files are not ingestion authorities.

The API resolves all archive paths through one validated configuration object before opening files. Document precedence once: explicit process options, explicit environment, selected config file, then documented defaults. Clients know the endpoint and logical archive identity, not a storage path they can override per request.

Provision a persistent archive identity marker. Startup verifies the configured root, expected identity and required mount; a missing mount must not create an empty local replacement. Initial provisioning is an explicit administrative action. Resolving symlinks is diagnostic, not permission to rewrite them.

Initially support one API writer process per archive. Enforce a lifetime ownership lock acquired before bootstrap/migration; fail startup for a second writer. Keep short transaction locks inside that process. All mutating maintenance commands must use the API or an explicit offline maintenance mode that acquires exclusive ownership with the service stopped. Verify locking on the actual filesystem; do not assume local-filesystem behavior on NFS.

Audit every writer, including enrichment, title fixers, transcript updates/reconciliation, legacy pending-file handling, playlist writes, migrations, editor shortcuts, restore tools, cron jobs, and ad hoc scripts. Prevent supported helpers from bypassing ownership. Preserve the separate local-transcribe worker's ownership of its queue/output contract; do not fold that service into this repo.

Use atomic replacement and appropriate file/directory durability for whole-file rewrites. Locks must survive replacement of `references.md`; do not use the replaced inode as the sole coordination object. Slow network work stays outside short archive transaction locks.

### 4.2 Observable destinations

Add operator diagnostics, with command/endpoint names finalized in Phase 0. The intended information is:

| Process identity | Destination identity | Installation identity |
| --- | --- | --- |
| Host, role, PID, start time, actual executable, service unit | API endpoint, persistent archive ID, configured path, resolved path, mount identity, ownership status | Loaded version/build commit, installed-on-disk version, interpreter/prefix, pipx/venv/source provenance, enabled roles |

Report the source of each relevant setting, not just its value. Never dump whole environments, tokens, signed URLs, or credentials. Full physical paths belong in protected operator diagnostics or local status, not anonymous public health responses. Health must remain fast and must not contact GitHub per request.

Every ingest receives a correlation ID and an explicit canonical destination identity. The operator must be able to trace a Discord message to an API receipt and stored row without guessing from a venv name.

## 5. Unified ingestion, discovery, and acknowledgments

### 5.1 Structured persistence result

Stop inferring correctness from printed output. The core returns typed results after the archive operation succeeds; CLI formatting consumes those results, not the other way around.

Preserve current `POST /urls` clients through an additive/versioned transition. Define canonical URL, archive ID, record identity, outcome, skip reason, receipt ID, queued work IDs, and partial/background-work status. Specify duplicate behavior and idempotency explicitly. Do not make an HTTP 200 mean that every item was stored.

For Discord, use a persistent idempotency key based on channel/message identity and content revision. Reusing a key with a different payload must not silently reuse the old result. Submission retries after a lost response must return/reconcile the original receipt without duplicate archive rows or duplicate jobs.

An `added` result means a committed record; `exists` means the matching record was verified in the identified authoritative archive. `skipped` is a policy outcome, not proof of storage. Queue acceptance means durable queue state, not an in-memory task. Root persistence and required follow-up enqueue must be recoverable across crashes; partial success must be visible and resumable.

Refwatch may acknowledge/delete only after all intended message items have durable acceptable outcomes. For asynchronous enrichment, it need not wait for transcription or every child fetch, but the API must durably own the remaining work before acknowledgment. Failures, malformed responses, missing results, archive mismatch, or unpersisted work keep the message available for recovery. Default skipped-item policy: retain for review unless an explicit approved policy authorizes acknowledgment of that skip class.

### 5.2 Playlist policy to approve

Interpret 'ignore playlists' as 'do not traverse incidental playlists,' while preserving useful playlist reference links. This interpretation is PROPOSED, not a claim about the current implementation. A stricter discard policy would be a separate product decision.

| Input/context | Proposed behavior |
| --- | --- |
| YouTube video URL with both `v=` and `list=` | Capture the video only; playlist context never causes expansion. |
| Radio/mix URL with a video | Capture the video only; retain existing radio/mix protections. |
| Playlist-only URL, the sole explicit target of the user submission | Store playlist reference and expand through bounded durable jobs. |
| Playlist URL among several explicit message/batch targets | Store link only; no automatic expansion. |
| Playlist found in YouTube metadata, Reddit, or other discovered content | Store link only; never expand, even when it is the only discovered link. |
| Replayed receipt or retry | Preserve the original policy/context; retries cannot promote a child to a direct target. |

The batch/message context must reach the server intact. Sending each URL separately must not accidentally make every playlist appear to be a sole explicit target. Parent/root context also survives redirects, provider transitions, and durable queue reloads.

### 5.3 Preserve discovery, remove inconsistent recursion

YouTube: keep metadata-card/description discovery independent of transcript success; ignore timestamp-only chapters and self-links; keep durable retries and the existing 50-link default bound.

Reddit: retain discovery of the post's outbound links, but route each child through the same policy, destination validation, deduplication, skip rules, and receipt/queue machinery as a YouTube child. No direct recursive calls that drop provenance or suppression flags.

Recommended traversal budget: one discovery generation per explicitly submitted root, shared across providers. A child may be recorded/enriched but does not trigger unlimited further link discovery. This intentionally replaces implicit cross-provider recursion; approve and test the rule. Preserve community-post and existing provider behavior through characterization tests rather than losing them in the refactor.

Apply cycle detection, per-root fan-out limits, bounded retries/backoff, timeouts, observable failures and restart recovery. Direct playlist expansion has its own documented item/work budget and resumable progress. Do not let playlist or child work stall unrelated ingestion.

### 5.4 Discord capabilities that must survive

Move URL extraction, channel scoping, startup history processing, live messages, attachment handling, dry-run behavior, and operational journaling into the consolidated package.

Images/media must be durably captured through the API-owned storage path before a message containing them is deleted. A short-lived Discord attachment URL alone is not a durable attachment. Select bounded server fetch versus bounded authenticated upload during contract design; never forward the Discord bot token to an arbitrary URL. Verify MIME/type, size, completion, checksum, and safe naming.

Plain-text statements retain their existing capture capability through an API-owned channel-record store. They need not be forced into URL-shaped rows in `references.md`. Preserve message/item provenance and existing local records during migration. Adapter logs and a bounded delivery outbox may remain local operational state; they are not another reference archive.

Persist delivery/receipt state across restarts. Test backfill plus live events, partial multi-URL success, connection loss after server commit, edits, duplicate events, attachment expiry, deletion permission failure, and messages exceeding configured limits. Do not silently truncate a message and delete it as fully handled. Run only one production watcher for the channel during cutover.

## 6. Determine what is writing where

Phase 1 is mandatory before choosing a physical destination or authorizing migration. Begin on the known archive/watcher host, then inspect other known CLI/API/worker installations discovered from configurations and deployment records. No network scanning is required.

Record each installation/service: host, account, executable realpath, Python prefix, installed distribution/version/source, loaded process identity, user/system service unit and drop-ins, working directory, allowed environment settings, config file, endpoint, archive logical/resolved path, filesystem/mount, and writer/reader role.

Compare the interactive CLI environment with the actual running watcher and API environments. Reading an EnvironmentFile alone is insufficient: the running process may have inherited different values or predate changes. Inspect only an allowlist such as HOME, PATH, API endpoint, config selection and archive settings; never publish a raw `/proc/.../environ` dump.

Inventory `~/references`, the reported staging-references location, other configured roots, old deployment homes, known mounts, containers/bind mounts, and approved legacy locations. Resolve links and compare filesystem identity so two names for one archive are not mistaken for divergent copies. Conversely, a shared-looking path string on two machines does not prove shared storage.

For each distinct archive collect safe counts, schema/header version, size, modification time, checksum, parseability, URL identity sets, associated assets, pending/discovery jobs and last-writer evidence. Label inventory timestamps and account for files changing during read-only collection. Inspect relevant retained backups when evidence suggests missing records, but do not automatically merge every historical backup or resurrect intentionally removed references.

Produce a sanitized `docs/operations/storage-inventory.md` with unknowns explicit. Keep raw archives, message content, complete logs, sensitive environment material and machine-specific secret-bearing manifests outside Git. Reconcile the OpenCRT root/child timestamps, related rows and later writes where evidence survives. Do not trigger a production re-ingest to manufacture diagnostic evidence during this read-only phase.

Gate: verified topology, distinct-data comparison, proposed canonical destination and rollback constraints reviewed by the other agent and approved by Drae. No fixed production storage path is selected by this plan.

## 7. Lossless archive reconciliation and migration

### 7.1 Prepare, never concatenate

Build an offline, dry-run-first merger using the existing archive parser/format rules, not `cat`, line sorting, or live HTTP re-ingestion. Input paths are explicit and read-only. Inputs remain unchanged; output is a new candidate root plus a machine-readable reconciliation manifest.

Classify each input as production, genuine captures in a staging/legacy root, test fixtures, historical backup, or unknown. Include genuine stranded captures. Do not contaminate production with synthetic staging fixtures or resurrect explicitly deleted history by default. Exclusions require recorded evidence and approval, not a guess based on a domain name.

Every source record must map to a retained record, a verified duplicate, an explicitly approved exclusion, or a preserved unresolved/quarantined item. No silent parse drops. Migration approval requires zero unexplained losses and zero unresolved conflicts that could discard valuable data.

Deduplicate only under reviewed URL identity rules. Do not broadly strip query parameters, lowercase paths, or assume HTTP/HTTPS equivalence. Preserve timestamps, original forms, titles, provenance, metadata, transcript status and history. Prefer a validated existing transcript over an unavailable placeholder, but preserve competing valid assets/metadata as conflicts or versions rather than silently overwriting them. Preserve duplicate observations in the migration manifest when the canonical archive uses one row per identity.

Copy associated transcripts, enrichment cards, media, channel records and relevant state with checksums. Rewrite embedded paths only through an audited old-to-new mapping. Identical files may be reused; different bytes at the same destination are conflicts, not overwrite permission.

Discovery queues, retry state, transcript pending files and local-transcribe queue identities need explicit reconciliation. Never blindly concatenate state JSON, reuse conflicting job IDs, requeue completed transcription, or reset a queue UUID. Respect the external worker's state ownership and shared-output paths. Backups and provenance remain recoverable outside Git.

### 7.2 Rehearse and prove

Run the merger on synthetic conflict fixtures and a protected snapshot where permitted. Prove deterministic output from the same inputs, idempotent rerun behavior, complete row accounting, unchanged input hashes, valid schema, valid asset references, no duplicate work, and a tested restore.

When two production-facing paths resolve to the same archive and no stranded captures exist elsewhere, record a verified migration-not-needed result rather than rewriting data unnecessarily. Centralize configuration and disable competing writers regardless.

### 7.3 Authorized cutover

Before mutation, Drae approves the exact destination, input manifest, conflict resolutions, backup set, maintenance scope and rollback procedure.

Quiesce all identified writers/producers and relevant workers, not just refwatch. Block new writes or keep incoming Discord messages retained. Acquire maintenance ownership, capture final deltas and a consistent backup, and rebuild/verify the final candidate. Do not swap symlinks underneath active writers or open archive handles.

Switch the API's explicit configuration to the verified canonical root. Start the single writer, verify identity/health/queues, then start the single consolidated watcher and restore client access. Validate exact rows and assets through API reads and server-side inspection. Observe the retired locations and prove they receive no new application writes.

Rollback must preserve any writes accepted after cutover. Never restore an older backup over newer captures. Quiesce again, retain and reconcile post-cutover deltas, then restore the previous service/configuration and compatible data state. If the old version cannot read the new format, the rollback procedure must explicitly account for that before release.

Retain old archives and installation backups read-only for an approved retention period. Deletion is separate authorization.

## 8. GitHub freshness checks and accurate upgrade guidance

Use the `ol` design as a behavioral reference: cached, bounded checks and useful notifications. Do not copy its literal-version lookup: ref's version is generated by setuptools_scm. Also do not use the current working directory's unrelated Git repository as a fallback source of version truth. [S11-S13]

### 8.1 Determine what is installed

Inspect the running distribution with importlib metadata, build provenance and `direct_url.json`; inspect pipx metadata when actually present. Record the interpreter and installation prefix. A directory named `ref-api` is not proof that pipx owns it. Direct URL metadata can distinguish VCS revision/commit and editable/local origins. [E1]

Classify pipx, dedicated venv, editable checkout, pinned wheel/tag/commit, and unknown/system-managed installations. Preserve extras, injected packages, package indexes, interpreter selection and install source. Detect when a service still runs old loaded code after the on-disk package changed.

The API reports its own update status. The CLI distinguishes its local package from the remote server; installing an update on the laptop must not be presented as updating the archive server. A shared pipx environment with both services requires instructions identifying both affected units.

### 8.2 Define latest by channel

| Installation channel | Comparison |
| --- | --- |
| Stable release | Latest eligible non-draft, non-prerelease release, with validated version ordering and a real installable artifact/source. |
| Opted-in prerelease | Latest eligible prerelease/release according to the selected channel. |
| Tracking GitHub branch | Installed build commit versus current tracked branch, with ahead/behind/diverged/unknown distinguished. |
| Pinned tag/commit/wheel | Report the pin and newer availability; do not silently change tracking policy. |
| Unknown provenance, offline or rate-limited | Report unknown/stale with last successful check; never claim current. |

A release tag, GitHub release, branch head and PyPI publication are different facts. Check the source used by the actual install before generating an upgrade command. Use Python-compatible version comparison; an invalid version is unknown, not automatically outdated. [E2]

Suggested defaults: a 24-hour successful-check cache, short bounded network timeout, backoff for failures, explicit refresh, and an opt-out. Perform automatic checks outside ingest requests and without delaying service readiness. Cache failure/corruption must not break capture. Avoid repeated warning spam and keep `ref --url-dump` stdout machine-readable.

### 8.3 Generate instructions, not surprises

For pipx, derive commands from the real installed package/source and local pipx capabilities. Account for injected dependencies and extras; pipx supports upgrading injected packages with the relevant option, but test the generated sequence against supported pipx versions. Do not inject a different PyPI copy over a VCS-installed server just to obtain dependencies. [E3]

For a dedicated venv, name its exact interpreter and approved target artifact/source. For editable installs, report checkout/branch/dirty state and delegate Git changes to the owning agent. For pinned installs, show a pin-preserving status and a separately explicit candidate upgrade. For unknown/system-managed installs, stop at diagnosis rather than recommend global pip.

Never recommend `sudo pip` or global pip. Never run an upgrade or restart from a freshness notification. Existing explicitly invoked upgrade behavior must be reconciled with this instruction-only check, not accidentally invoked by it.

An actionable instruction sequence identifies execution host/account, source/channel/target, environment, required extras, backup/maintenance preconditions, affected service restarts, and post-update verification. Preserve configuration, tokens, archive identity and queue state. Commands must be properly quoted and must not expose credential-bearing package URLs.

Test the real lifecycle in isolated pipx homes and venvs: install old artifact, detect newer artifact, follow generated instructions, preserve role dependencies, restart test services, verify the loaded version, and verify detection changes to current. Mocked comparison tests alone are insufficient.

## 9. Consolidating refwatch without losing capabilities or private data

The inspected ref repository is public and refwatch is private. Do not import private history wholesale. Recommended import: a reviewed, secret-scanned source/test snapshot with attribution and the exact upstream SHA, retaining the old private repo as provenance until retirement. Import relevant history only after an explicit full-history privacy/license review and separate approval.

Exclude `.env`, tokens, journals, channel content, downloaded images, local databases/outboxes, runtime archives, virtual environments and machine-local configuration. Verify licensing/permission before publishing the snapshot. Preserve relevant source and tests; do not just copy the README, whose feature description may lag the code.

Retain the `refwatch` command and `python -m refwatch` compatibility where practical. Document the transition away from `REFWATCH_REF_COMMAND` to explicit API configuration; reject obsolete/conflicting settings with an actionable message rather than silently launching a CLI. Do not retain an automatic subprocess/local-storage fallback.

Move existing async tests, ruff and mypy checks into the combined verification gate. Keep optional dependencies and console entrypoint behavior correct in both wheel and source installs. Test removing the old standalone package so that competing `refwatch` entrypoints cannot shadow the consolidated one.

Archive/redirect the old repository only after verified production cutover and Drae's approval. Do not delete it or change its visibility during this plan.

## 10. Security and operational requirements

'Run from anywhere' means authorized network access, not exposing the current unauthenticated API to the public Internet. Select and test a trusted VPN/private-network deployment; require authentication and transport protection before any wider exposure. Preserve the bot token in protected service configuration outside Git. The current app explicitly says authentication is not enabled. [S4]

Apply server-side URL policy to direct and discovered work, with explicit operator allowlisting for intentional internal targets. Check resolved destinations and redirects, not only URL text; bound network time, response sizes, attachments, recursion and work volume. Audit legacy external-command calls so untrusted URLs never become shell commands. Existing description-side filters are not a complete server boundary. [S15]

Expose queue backlog, oldest pending age, failed jobs, last successful capture, archive identity, version/build and storage readiness. Correlation should work without raw secret-bearing URLs in logs. Document recovery for DNS/API outage, disk full, corrupt queue/cache, missing mount, expired attachment and Discord permission failure.

Keep diagnostics, backup/restore and migration fixtures sanitized. No live Discord token or production archive in CI. Staging must have a different archive identity and must not consume/delete production-channel messages. Add checks that reject production/staging path aliasing.

## 11. Agent coordination, gates and repository records

Read root `AGENTS.md` and `project_spec.md` when present, `.codex/AGENTS.md`, relevant task files, `HANDOFF.md`, and `HANDOVER.md` before work. At the inspected baseline there is no root AGENTS.md/project_spec.md; Phase 0 adds or reconciles small entrypoint documents rather than inventing historical content.

`HANDOVER.md` is the bilateral Pi/OpenCode execution log: append claims, decisions/questions, evidence, review outcomes and next action. `HANDOFF.md` remains the project index with a concise current-state pointer. Do not maintain two competing detailed status logs. Retain historical material and append corrections instead of rewriting evidence.

Each claimed task has one owner, a dedicated branch/worktree and a task file in `.codex/tasks/wip/`. On complete verification move it to `review/` with matching status. Only after approval move it to `done/`. Record task ID, owner, scope, dependencies, acceptance checks, exact commands, outcomes, limits, tested commit and next action. Use an append-only `docs/DECISION_JOURNAL.md` for accepted consequential decisions.

Start from updated main; fetch and fast-forward through the agent workflow, never discard unrelated changes. Use small Conventional Commits, commit and push intended work, and record the remote SHA. No direct main commits, forced shared-branch rewrites, unauthorized task takeover or automatic phase advancement.

The non-owning agent independently reviews; ChatGPT inspects pushed diffs and evidence before recommending acceptance. Drae authorizes scope, merges and production actions. Agents stop after pushing verified review work. Merge, branch/worktree cleanup, release and deployment each require the applicable authorization. An evidence entry identifies the commit actually tested, not an impossible self-referential hash of the file containing it.

Shared-file changes, especially packaging, API schemas and HANDOVER, are serialized by the designated integration owner. Each agent appends its own handover entry in its branch; integration reconciles both entries without overwriting the other's work. Freeze shared interfaces before parallel work. Baseline failures are documented and resolved or explicitly re-scoped by Drae; agents cannot waive or weaken required checks themselves.

### Master phase checklist

All boxes start unchecked. An implementation box requires deliverables and exact evidence; a verified box requires independent review of that evidence. Checking a box is not a substitute for the linked task and tested SHA. 'Done' additionally requires the approved merge and applicable deployment/cleanup.

| Phase | Owner / independent reviewer | Branch | Deliverable and stop gate |
| --- | --- | --- | --- |
| P0 Governance and decisions | Pi / OpenCode | `docs/ref-consolidation-contract` | Reconcile docs, approve policies/interfaces and evidence rules; stop before application changes. |
| P1 Runtime inventory and baseline | Pi / OpenCode | `audit/ref-storage-topology` | Read-only topology, archive comparison, baseline checks and migration proposal; stop before host changes. |
| P2 Single-writer core and API contract | OpenCode / Pi | `feat/ref-authoritative-archive` | Explicit configuration/identity, client purity, ownership, typed persistence/receipt and event/media contracts; stop at review. |
| P3 Unified discovery policy | OpenCode / Pi | `feat/ref-discovery-policy` | Shared YouTube/Reddit/playlist context, bounded durable jobs, characterization/regression tests; stop at review. |
| P4 Consolidated Discord client | Pi / OpenCode | `feat/ref-discord-client` | Reviewed import, direct HTTP, durable delivery, attachments/statements, async gates; stop at review. |
| P5 Versions, packaging and upgrades | OpenCode / Pi | `feat/ref-install-aware-updates` | GitHub/channel checks, provenance, safe instructions, wheel/pipx upgrade tests; stop at review. |
| P6 Migration tool and rehearsal | Pi / OpenCode | `feat/ref-archive-reconciliation` | Offline merger, manifests, conflict accounting, snapshot rehearsal and rollback proof; stop before production mutation. |
| P7 Integrated release candidate | OpenCode / Pi | `release/ref-consolidation` | Complete gate, isolated end-to-end tests, version/changelog/docs/artifacts and reviewed deployment runbook; stop before publishing/deploying. |
| P8 Authorized cutover and closure | Pi / OpenCode + ChatGPT | `ops/ref-consolidation-cutover` | Separately approved publication, installation, data cutover, live smoke, observation, retirement and final evidence. |

- [ ] P0 deliverables complete
- [ ] P0 independently verified and decisions approved
- [ ] P1 deliverables complete
- [ ] P1 independently verified and canonical destination approved
- [ ] P2 deliverables complete
- [ ] P2 independently verified
- [ ] P3 deliverables complete
- [ ] P3 independently verified
- [ ] P4 deliverables complete
- [ ] P4 independently verified
- [ ] P5 deliverables complete
- [ ] P5 independently verified
- [ ] P6 deliverables complete
- [ ] P6 independently verified and migration manifest approved
- [ ] P7 deliverables complete
- [ ] P7 independently verified; release/deployment authorization recorded
- [ ] P8 cutover complete
- [ ] P8 production acceptance, cleanup and closure independently verified

Dependencies: P0 -> P1 -> P2. After the P2 interface gate, P3 and P4 can run in separate worktrees. P5 and P6 can run in parallel after their required interfaces stabilize, with packaging ownership serialized. P7 requires P2-P6 accepted. P8 requires explicit approval of P7 and the final migration/rollback manifest. Do not perform Phase 8 because the code phases happened to finish.

### Required verification matrix

| Area | Required evidence |
| --- | --- |
| Destination/configuration | Environment/config precedence; symlink identity; wrong/missing mount fail-closed; wrong archive ID rejected; second writer rejected; no production/staging alias. |
| Pure clients | In a fresh isolated HOME, CLI and Discord make API calls without creating/migrating a local archive or importing server workers; API outage never switches to local writes. |
| Concurrent persistence | Concurrent URL adds, enrichment, transcript reconciliation and maintenance attempt produce no lost rows; crash-safe rewrite and disk-full paths are exercised. |
| Result correctness | No stdout-based success; per-item results cover every submitted target; injected write/queue failure cannot produce a false durable acknowledgment. |
| YouTube/Reddit | Equivalent inputs through both clients create equivalent records and child jobs; transcript failure does not disable discovery; skip policy applies to children. |
| Playlist semantics | Video-plus-list, radio mix, sole explicit playlist, multi-target playlist, discovered playlist, redirect-to-playlist and retries all obey the approved table. |
| Traversal safety | Cycle/depth/fan-out bounds hold across provider boundaries; child jobs cannot regain direct-root privileges. |
| Discord durability | Backfill/live duplication, restart, response lost after commit, partial messages, edited messages, truncation limits and delete-permission failure are recoverable without loss. |
| Media/statements | Attachment bytes/checksum and plain-text records survive service restart; expired/incomplete attachments prevent unsafe deletion. |
| Data merge | Every source row accounted for; inputs unchanged; transcript/metadata conflicts preserved; deterministic/idempotent run; staged fixtures excluded by approved manifest only. |
| Queue migration | Existing jobs/UUIDs/completed work remain valid; no unapproved retranscription or lost pending work. |
| Update detection | Stable/prerelease/branch/pin/ahead/diverged/offline/rate-limited/corrupt-cache cases; client and server versions not conflated. |
| Installation | Clean wheel/sdist install, correct packages/entrypoints, base/api/discord/combined roles, supported Python matrix, pip check, actual old-to-new pipx and venv upgrades. |
| Compatibility | Existing URL dump output purity, search/list/backup/transcript/provider helpers and published API contracts retain documented behavior or have an approved migration path. |
| Security | Secrets scan, sanitized logs, URL/redirect/network policy, no shell injection, bounded uploads and approved network exposure. |
| Full gate | Full pytest suite plus retained Discord pytest-asyncio/ruff/mypy, syntax checks, integration and packaging checks, CI on exact reviewed/merged SHAs. |
| Production | Approved real Discord and remote-CLI submissions appear in the same identified archive; children complete or remain visibly durable; retired roots stay unchanged. |
| Release/rollback | Tag and publication/install channel verified, actual running build verified after restart, restore/cutover-delta procedure tested, approved branch/worktree cleanup verified. |

No numerical test-pass count is asserted by this plan. Baseline and final counts must come from actual executions, with commands and environments recorded.

## 12. Decisions requiring approval before implementation

| ID | Proposed decision | Approval point |
| --- | --- | --- |
| D1 | One production API writer; normal clients require API configuration; explicit offline maintenance only. | P0 |
| D2 | Keep Markdown archive; add only necessary durable receipt/provenance state, not a database rewrite. | P0 |
| D3 | Incidental playlists are link-only; video wins over list context; expansion only for sole explicit playlist target. | P0 |
| D4 | One discovery generation per root, consistent across providers; bounded playlist expansion. | P0 |
| D5 | Preserve images and statements centrally; durable API acknowledgment before Discord deletion. | P0 |
| D6 | Python 3.11 proposed floor and 2.0.0 proposed release; finalize against measured installations. | P1/P5 |
| D7 | Sanitized refwatch snapshot import with provenance, not automatic publication of private history. | Before P4 import |
| D8 | Exact canonical storage host/root, selected input archives, exclusions, conflict decisions and retention. | P1/P6, revalidated before P8 |
| D9 | Installation/channel policy per host, protected network access, and affected-service restart plan. | P5/P7 |

Record accepted/rejected/amended decisions in `docs/DECISION_JOURNAL.md` with authorizer, rationale, evidence and superseding decision when needed. Unapproved proposed decisions must not be presented as deployed behavior.

## 13. First agent handoff

### Pi: P0 and P1 only, after Drae authorizes those phases

Read the repository instructions and both handover files. Review this plan and the planning PR. Claim P0 before editing; create a dedicated branch from updated main, preserve unrelated files, and reconcile the root documentation contract. Do not implement application changes. Push P0 for OpenCode/ChatGPT review and stop.

After P0 approval and a separate P1 authorization, claim `audit/ref-storage-topology`. Perform the read-only inventory in section 6 and collect baseline verification in isolated environments. Determine actual service/client installations, effective configuration, resolved archive identities and distinct data sets. Identify every writer and propose the canonical destination and migration inputs. Do not restart services, change configuration, re-ingest production URLs, delete Discord messages, upgrade packages, or alter archives. Keep raw sensitive evidence outside Git; commit sanitized findings, task evidence and HANDOVER updates. Push, move the task to review, and stop.

Success: a reviewer can explain where each active path writes, whether the reported paths alias the same file, what data differs, and exactly what remains unknown. An unproven incident cause is reported as unproven.

### OpenCode: independent P0/P1 review, no implementation yet

Read the same instructions, plan, task files and HANDOVER entries. Inspect Pi's pushed commits and original command evidence. Independently validate topology/path reasoning, installed-versus-source comparisons, lossless-merge requirements, privacy exclusions and the proposed discovery/acknowledgment contracts. Run safe verification where access permits. Do not modify Pi's task or production. Append review findings with exact commit references and verification limits on your dedicated review branch, commit/push and stop. Application work starts only after the corresponding phase is authorized.

## 14. Evidence sources

Pinned source links are evidence of code behavior, not live deployment proof.

- S1: [ref archive/config initialization](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/cli.py#L338-L431)
- S2: [CLI ingestion and bootstrap ordering](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/cli.py#L3279-L3341)
- S3: [API endpoint selection](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/api_client.py#L29-L37)
- S4: [API bootstrap, health and authentication description](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_api/app.py)
- S5: [process-local archive lock](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/archive_lock.py)
- S6: [YouTube discovery and queued child handling](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_api/service.py#L157-L410)
- S7: [general capture, Reddit recursion and playlists](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/cli.py#L2463-L2660)
- S8: [YouTube list/video precedence and link-only playlists](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/cli.py#L1179-L1313)
- S9: [stdout classifier](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_api/service.py#L93-L104) and [API schemas](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_api/schemas.py)
- S10: Private-repository baseline `draeician/refwatch@6697a9c4c5ce143e21caf027fdb2db40e420e373`: `src/refwatch/handler.py`, `runner.py`, `queue.py`, `images.py`, `record.py`, `config.py`. Publication of their contents/history requires the P4 privacy gate.
- S11: [existing ref install-aware upgrade code](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/upgrade.py)
- S12: [ol version management reference](https://github.com/draeician/ol/blob/e2433f0861b64fb09cb08fcdf1b74e2251e8dc9b/src/ol/version.py)
- S13: [ref packaging and dynamic versioning](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/pyproject.toml)
- S14: Private-repository baseline above: `pyproject.toml` (Python >=3.11, discord.py/pydantic-settings, async tests, ruff/mypy).
- S15: [existing discovery filters and their stated limits](https://github.com/draeician/ref/blob/80c6e379106a73c047cd517e56207bc62d558d7f/src/ref_cli/youtube_extract.py)
- E1: [Python packaging direct URL origin](https://packaging.python.org/en/latest/specifications/direct-url/) and [data structure](https://packaging.python.org/en/latest/specifications/direct-url-data-structure/)
- E2: [GitHub releases API](https://docs.github.com/en/rest/releases/releases) and [Python version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- E3: [pipx installed-app management](https://pipx.pypa.io/stable/how-to/manage-installed-apps.html) and [CLI reference](https://pipx.pypa.io/stable/reference/cli.html)
