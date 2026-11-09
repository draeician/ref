# [fix] Route remote clients through ref-api and harden queue producer reporting

- **Task ID:** f7774dc0
- **Owner:** OpenCode
- **State:** REVIEW
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/review/`.
- **Branch:** `fix/remote-api-queue-producer`
- **Base:** `origin/main` = `377dc34160a78d7e8c601dbad3bdeb7a92f2f7a8`
- **Repositories:** `draeician/ref` (implementation); `draeician/local_transcribe` (read-only unless a verified producer defect requires a linked change).
- **Authorization:** Implement, test, document, commit, push, and open draft PRs. **No** production deployment, live config edit, queue mutation, service restart, or merge during implementation.

## Claim

```
[CLAIM] f7774dc0 remote-client routing + queue producer reporting
repo: draeician/ref@fix/remote-api-queue-producer
actor: OpenCode  role: Coder
task-file: .codex/tasks/review/f7774dc0-remote-api-queue-producer.md
plan:
- Route all remote-capable CLI operations through ref-api before local bootstrap/logging
- Add exact missing-api guidance; remove local fallbacks and credential prompt
- Guard missing YouTube credentials; sanitize/bound queue-failure text
- Add regression coverage for routing, queue fallback, and identity behavior
- Verify full gate, push branch, open draft PR, move to review/
```

## Review corrections claim (2026-11-09)

```
[CLAIM] f7774dc0 review corrections on PR #33
reviewed-head: 0c73cc8d2cd0999a37ccf2a5186a6e18155d6937
branch: fix/remote-api-queue-producer
state: REVIEW (stays in .codex/tasks/review/)
plan:
- Report missing api_url as unconfigured and exit nonzero from ref --status
- Extract the actionable queue error ahead of the full Deno guidance block
- Correct README to describe required ref-api routing and worker-only dependencies
- Re-run full verification, push, update HANDOFF, confirm exact-head CI
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

## Review evidence (2026-11-09)

- Draft PR #33: https://github.com/draeician/ref/pull/33
- Implementation `2ccde1d60f27224ade641fdd77de4590634c1e80`
- Tests `4e86bd5d1206b84513b783db2c0d3bf9c155dc08`
- Docs/task `ed60037ba294db7617e6e32e846bc39f7af273c3`
- Review-state move `cb81789e735b38722664c7bbecbadcce492f9b87`
- Exact-head CI on `cb81789`: workflow `tests`, run `42689895217`, success.
- Ref suite: 594 passed, 1 warning. Focused routing/queue/reconcile: 109 passed.
- `local_transcribe` focused: 60 passed; read-only simulation confirmed the stale
  config mismatch and that a corrected config enqueues without a Deno probe.
- No deployment, live config edit, queue mutation, service restart, or merge.

## Review corrections evidence (2026-11-09)

Reviewed head: `0c73cc8d2cd0999a37ccf2a5186a6e18155d6937`. Task remains in
`.codex/tasks/review/` with State `REVIEW`.

### Correction 1 — `ref --status`

- `src/ref_cli/api_client.py`: missing `api_url` now prints
  `Mode: unconfigured (api_url is not set)` plus
  `Status: error (no ref-api endpoint configured)`, actionable server/client
  setup steps, and returns `1`. Healthy configured API returns `0`; configured
  unreachable API returns `1`.
- Tests: `tests/test_api_client.py` (`test_report_api_status_unconfigured`,
  healthy, unreachable) and `tests/test_remote_client_routing.py` main-level
  tests assert exit codes and no `.config`/`references` creation.

### Correction 2 — queue stderr summarization

- `src/ref_cli/cli.py`: added `_summarize_queue_cli_stderr()`. Full stderr stays
  in the server log; the saved reference receives a bounded one-line summary
  beginning at the first strong queue/UUID/mismatch/identity line with Deno
  guidance removed. UUID validation and pending-file "not queued" fallback are
  unchanged; unrelated errors are not hidden by broad filtering.
- Test: `test_lt_failure_saved_reference_prefers_queue_error_over_deno_guidance`
  replays the full Deno block + UUID mismatch and asserts the saved status has
  the mismatch/both UUIDs, no Deno guidance, one bounded line, "not queued",
  `transcript-pending.md`, while the full stderr remains logged.

### Correction 3 — README

- `README.md` now distinguishes current required-`ref-api` behavior from
  historical pre-API local-only installs; states `api_url` is not optional,
  missing API never means local ingestion, `ref --status` reports unconfigured
  as an error, the API is authoritative, explicit local maintenance commands
  keep their behavior, and only worker hosts need download/transcription
  dependencies.

### Verification (exact)

| Check | Command | Result |
| --- | --- | --- |
| Focused | `pytest -q tests/test_api_client.py tests/test_remote_client_routing.py tests/test_transcript_queue_modes.py` | 59 passed |
| Full | `python -m pytest -q` | 597 passed, 1 warning |
| Syntax | `python -m compileall -q src tests` | exit 0 |
| Build | `python -m build --wheel` | wheel built |
| Missing API | clean venv, empty HOME, `ref --status` | exit 1, guidance, no files |
| Healthy API | local `/health`, `REF_API_URL` | exit 0, `Status: ok`, no files |
| Unreachable API | `REF_API_URL=http://127.0.0.1:18998` | exit 1, `Status: unreachable`, no files |
| Whitespace | `git diff --check` | clean |
| Secret scan | regex over `git diff` | no credentials |

No merge, deployment, live config change, pipx upgrade, queue modification, or
service restart was performed.
