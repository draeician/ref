# [fix] Route remote clients through ref-api and harden queue producer reporting

- **Task ID:** f7774dc0
- **Owner:** OpenCode
- **State:** WIP
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/wip/`.
- **Branch:** `fix/remote-api-queue-producer`
- **Base:** `origin/main` = `377dc34160a78d7e8c601dbad3bdeb7a92f2f7a8`
- **Repositories:** `draeician/ref` (implementation); `draeician/local_transcribe` (read-only unless a verified producer defect requires a linked change).
- **Authorization:** Implement, test, document, commit, push, and open draft PRs. **No** production deployment, live config edit, queue mutation, service restart, or merge during implementation.

## Claim

```
[CLAIM] f7774dc0 remote-client routing + queue producer reporting
repo: draeician/ref@fix/remote-api-queue-producer
actor: OpenCode  role: Coder
task-file: .codex/tasks/wip/f7774dc0-remote-api-queue-producer.md
plan:
- Route all remote-capable CLI operations through ref-api before local bootstrap/logging
- Add exact missing-api guidance; remove local fallbacks and credential prompt
- Guard missing YouTube credentials; sanitize/bound queue-failure text
- Add regression coverage for routing, queue fallback, and identity behavior
- Verify full gate, push branch, open draft PR, move to review/
```

## Incident A — remote client routing

Observed on nomnom: `ref --status` reported `Mode: local (api_url not set)`, and
`ref <YouTube URL>` fell through `run_ingest → process_url → get_youtube_data`
until `google.auth.exceptions.DefaultCredentialsError`. A remote client must
never take the archive-writer path.

### Required behavior

- Ingest (URL, YouTube ID, interactive, file), search, transcript, list, and
  URL dump require a configured ref-api endpoint.
- Missing `api_url` prints the exact server/client guidance, exits nonzero, and
  raises no traceback. It never silently falls back to local processing.
- An unreachable API exits nonzero and never triggers local fallback.
- A configured API receives the original input URL.
- Remote clients do not require Google credentials, transcript queues, Deno, or
  worker dependencies.
- Routing happens before archive bootstrap/migration, local file logging,
  YouTube metadata, Google calls, queue access, or enrichment writes.
- `ref-api` server-side processing remains the authoritative archive writer.
- Explicit server management/inspection (`--install-server`,
  `--uninstall-server`, `--server-status`, `--status`, `--upgrade`) and
  user-requested backup/export (`--backup`) keep their behavior. On the archive
  host, backup uses the local file for loopback `api_url`.
- Config bootstrap/upgrades must preserve an existing `api_url` and must not be
  invoked by read-only remote routing.

### Implementation plan

1. Add a non-mutating config read (`read_config_for_routing`) used only for
   routing decisions; keep `load_config()` (bootstrap + migration) for
   server-side/local archive operations.
2. Add `require_api_base_url()` with the exact guidance text and exit code 1.
3. Make import-time logging stream-only; enable file logging lazily only for
   local archive operations (`--integrity`, local `--backup`).
4. Dispatch remote operations in `main()` before archive bootstrap/migration.
5. Remove local fallbacks from `run_ingest`, `run_file_ingest`, `run_search`,
   and `run_transcript`; extract `run_interactive` with the same requirement.
6. Remove the `YOUTUBE_API_KEY` interactive prompt from `__main__`.
7. Raise a controlled `YouTubeCredentialsError` when server-side metadata needs
   `YOUTUBE_API_KEY`; `process_url` reports it without a traceback.
8. Update `ingest_file_via_api` to use the non-mutating config read so an
   env-only client does not create `~/.config/ref/config.yaml`.

## Incident B — transcription producer reporting

Observed: archive capture, enrichment, and show-note discovery succeeded, but
transcription failed with `Local-only transcript mode.`, an `lt queue add`
exit 1, a Deno warning, and a queue UUID mismatch.

### Read-only production findings (minion-26, 2026-11-09)

- Actual queue `/opt/md2/music/youtube/transcripts/transcription-queue`,
  `queue.id` UUID `8c6fc098-8cbe-41ae-9689-dd759797a582` (created by `nomnom`).
- `~/.config/ref/ref-api.env` correctly pins the same UUID and absolute queue.
- Stale `~/.config/local-transcribe/config.yaml` pins
  `queue.path: /tmp/lt-smoke-queue-59553` and
  `expected_uuid: 6a058908-116f-41c9-987f-d5f4ef38667e`.
- Installed `lt` is `local-transcribe 0.7.0` from VCS commit
  `25b89f1326751a3b0781051331822c50ffde3b19`; `local_transcribe/main` is
  `0.8.1` at `b3cf22ee5da337fab9dcd37fb97506f5beab012b`.
- The Deno warning comes from the 0.7.0 root Typer callback calling
  `check_deno_with_guidance()` for every subcommand. `main` fixes this in
  `0e83077`, `8423007`, and `6a2078d`, with
  `tests/test_deno_startup_warnings.py`.
- The UUID mismatch comes from the stale config: `resolve_queue_dir()` applies
  `queue.expected_uuid` even when `--queue-dir` is supplied. The project's
  deployment preflight (task 043) documents this as intentional fail-closed
  pinning and requires correcting the live config, not bypassing it. **Decision:
  no `local_transcribe` code change**; record precise deployment remediation.

### Implementation plan

1. Keep the durable queue path and identity checks unchanged.
2. Collapse multiline `lt queue add` stderr into a bounded one-line summary for
   the saved reference; log full stderr server-side.
3. Make pending-file fallback explicitly say it is **not queued** and is
   recorded in `transcript-pending.md`.
4. Preserve the successful reference when enqueue fails.
5. Confirm and document that `transcript-pending.md` entries are not
   automatically recovered by `transcript_reconcile` (which only matches durable
   queue placeholders); recovery is `ref --transcript` after the queue is fixed.
6. Keep show-notes discovery status independent of transcription status.

## Regression coverage (15 required cases)

1. Missing `api_url` clean guidance + nonzero exit.
2. No local archive/config/log/queue creation on remote-only ingest.
3. No Google API call with missing configuration.
4. Configured API ingest uses HTTP only and receives the original URL.
5. Unreachable API exits without local fallback.
6. Interactive and file ingestion obey routing.
7. Server-internal `process_ingest` remains functional.
8. Missing provider credentials yield a controlled error.
9. Queue-only producer never probes Deno (local_transcribe regression suite).
10. Producer works when Deno is absent (local_transcribe regression suite).
11. Queue identity mismatch remains fail-closed.
12. Valid queue identity allows normal enqueue.
13. Queue failure preserves durable pending fallback.
14. Pending recovery status is accurately reported.
15. Existing enrichment/show-note behavior remains.

Simulation uses temporary `HOME`/XDG directories and fake dependencies. Tests
must never touch production archives or queues.

## Verification gate

Full pytest, focused routing/queue/reconcile tests, lint/syntax, package build,
isolated pipx/venv smoke, real CLI behavior checks, `git diff --check`, and a
secret scan. Record exact commands, exit codes, and environmental limits.

## Decisions and rejected approaches

- **Rejected:** local fallback for remote clients, even when ref-api is installed
  on the same host. The architecture is `client → HTTP → ref-api → archive`.
- **Rejected:** prompting for `YOUTUBE_API_KEY` in the CLI entry point; that path
  belongs on the server and breaks remote clients.
- **Rejected:** overwriting `queue.id`, disabling identity validation,
  initializing a replacement queue, deleting jobs, forcing a producer onto
  another queue, or editing live config.
- **Rejected:** modifying `local_transcribe.resolve_queue_dir()` to let
  `--queue-dir` bypass `expected_uuid`. The existing fail-closed behavior is
  documented and intentional; the defect is stale configuration.
- **Kept:** `ref-api` server-side processing and explicit backup/export.
- **Kept:** fail-closed queue identity validation in both repositories.

## Definition of done (for the review handoff)

Code, tests, task, HANDOFF, and agent lifecycle instructions updated together;
full verification gate recorded; draft PR open; task moved to
`.codex/tasks/review/` with State `REVIEW`. Merge/deploy remain unauthorized.
