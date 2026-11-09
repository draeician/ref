# [fix] Make `ref --upgrade` strictly read-only and topology-aware

- **Task ID:** b1255911
- **Owner:** OpenCode
- **State:** REVIEW
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/review/`.
- **Branch:** `fix/upgrade-instructions-detection`
- **Baseline:** `origin/main` = `80c6e379106a73c047cd517e56207bc62d558d7f`
- **Implementation commit:** `39d7b3510d6d5da63d31b37fa424ce52d294995f`
- **Review-correction commit:** `63395ce84c00a2684e8532b2e227e9c0f05d2d80`
- **Evidence commit:** `e5155acc6194bfb2e7090dd51a088f2676b03240`
- **Verified remote head before review corrections:** `234b6747fc4686a9515410beef25fb643cde9d9b`
- **Authorization:** implementation, tests, commit, push, draft PR. **No merge, deployment, production package change, or service restart.**

## Original problem and root cause

On `minion-26`, the CLI and API are separate installations:

- CLI launcher: `/home/draeician/.local/bin/ref`
- Resolved executable: `/home/draeician/.local/share/ref-services/ref-api/bin/ref`
- Dedicated service venv: `/home/draeician/.local/share/ref-services/ref-api`
- User service: `ref-api.service`, `ExecStart=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000`
- Separate pipx install: `ref-cli` from `git+https://github.com/draeician/ref`

The old implementation assumed the running interpreter had a `pipx_metadata.json`
under `sys.prefix`. That is false for the dedicated service venv, so
`ref --upgrade` printed `Install source: not detected as a pipx venv.` It also
had a `perform_upgrade()` path that ran `pipx`, `pipx inject`, and
`systemctl --user restart ref-api`, contrary to the required read-only behavior.

## Review corrections (rejection follow-up)

The first review rejected the branch for four findings. All four are corrected in
commit `63395ce84c00a2684e8532b2e227e9c0f05d2d80`; existing commits are preserved.

### Correction 1 — running API version

`ref --upgrade` previously inspected only the installed ref-api package. It now
performs one bounded, read-only `GET` against the local `/health` endpoint
(2 s timeout). Endpoint selection order is: explicit `health_url` argument,
configured loopback `api_url` from `~/.config/ref/config.yaml`, then the
`ExecStart`-derived service health URL. Non-loopback configured URLs are ignored.

`check_running_api()` records reachability, HTTP status, version, and the Git
revision parsed from the version string. `evaluate_running_api()` compares the
running revision/version with the installed ref-api package:

- Same revision/version → `current`.
- Different revision/version → `stale`.
- Unreachable, non-JSON, missing version, or uninspectable install → `unknown`
  **never** `current`.

When the package is current but the running process is stale, the only action is
an explicit user-controlled `systemctl --user restart ref-api.service`. No restart
is ever executed. An unreachable runtime adds an unresolved status, so the report
cannot print "Nothing to do" or claim the running service is current.

### Correction 2 — Git revision relationship

`compare_revisions()` no longer maps any nonmatch to `outdated`. It now returns
`exact`, `different`, or `unknown` locally. `resolve_revision_relationship()`
then uses GitHub evidence:

- Exact/abbreviated prefix match → `exact`.
- GitHub compare `behind` → `outdated` (upgrade may be recommended).
- GitHub compare `ahead` → `ahead`; never recommend a downgrade.
- GitHub compare `diverged` → `divergent`; never recommend a downgrade.
- Missing GitHub evidence, unresolved abbreviated SHA, network failure, or
  malformed revision → `unknown`; no upgrade/downgrade command.

Abbreviated revisions are first resolved through
`GET /repos/{repo}/commits/{sha}` (cached per process), then compared with
`GET /repos/{repo}/compare/{latest}...{installed}`.

### Correction 3 — review lifecycle

The task now follows the required `wip/` → `review/` → `done/` directory
lifecycle. `.codex/tasks/wip/`, `.codex/tasks/review/`, and `.codex/tasks/done/`
exist; this record was moved with `git mv` (history preserved) to
`.codex/tasks/review/`, and its State is `REVIEW`, agreeing with the directory.

### Correction 4 — remote CI

Draft PR https://github.com/draeician/ref/pull/30 (base `main`) triggers the
existing `pull_request` workflow. Exact-head CI for
`903e89b8a88fc1142cbedbbc2f9638888fb8e5e7`: workflow `tests`, run `42660825495`,
conclusion **success** (pytest job 35s). The PR remains draft/open and is not
merged; CI protections are not changed.

## Implementation summary

`ref --upgrade` now only reads local metadata, the service unit, the local
`/health` endpoint, and public GitHub metadata, then prints instructions:

- Resolves the actual running executable/symlink and interpreter.
- Inspects the running environment's `ref_cli-*.dist-info`, `METADATA`,
  `direct_url.json` (PEP 610), `INSTALLER`, and `_version.py`.
- Independently discovers pipx installs from `PIPX_HOME`, XDG data home, and
  conventional pipx homes without assuming pipx owns the PATH executable; works
  when the `pipx` executable is absent.
- Parses `ref-api.service` `ExecStart`, identifies the service venv/interpreter,
  installed version/revision/source, and whether it is the same environment as
  the CLI.
- Queries GitHub for the repository default branch and latest commit SHA once,
  without credentials.
- Performs one bounded, read-only local `/health` request and reports the running
  API revision separately from the installed package and GitHub.
- Resolves full or abbreviated Git SHAs and uses GitHub compare evidence to
  distinguish exact, behind, ahead, divergent, and unknown relationships; refuses
  to recommend a downgrade merely because identifiers differ.
- Recommends a user-controlled service restart only when the installed code is
  current but the running process is stale; unreachable runtime is `unknown`.
- Distinguishes pipx Git, pipx PyPI, pipx local path, dedicated venv Git, local
  repository, editable, local wheel/artifact, and unknown provenance.
- Pins Git reinstall commands to the verified latest SHA; preserves `[api]` for
  service environments; distinguishes when a `systemctl --user restart` is
  required; prints verification and rollback guidance.
- If both installations are current, prints `Nothing to do` and recommends no
  reinstall. If only one is outdated, only that installation is addressed.
- Removed `perform_upgrade()` and all automatic command execution from the CLI.
- `--upgrade` is intercepted before archive bootstrap/migration. CLI import also
  skips `~/references/logs` file-handler creation for `--upgrade`, so the command
  writes no application data.

## Files changed

- `src/ref_cli/upgrade.py` — rewritten read-only detection, GitHub check,
  comparison, instructions, verification, rollback.
- `src/ref_cli/cli.py` — dispatch to `report_upgrade_instructions`; updated help;
  read-only logging setup for `--upgrade`.
- `tests/test_upgrade.py` — 47 regression tests, including actual `cli.main()`
  dispatch, no-mutation assertions, running-API stale/current/unreachable states,
  and ahead/behind/divergent/unavailable/unresolved-SHA relationship states.
- `README.md` — read-only behavior, split-environment restart guidance,
  provenance limits, rollback/archive warning.
- `.codex/tasks/b1255911-upgrade-instructions-detection.md` — this record.
- `HANDOFF.md` — appended evidence section.

## Decision Journal

1. **Read-only means no subprocess at all.** Detection parses pipx metadata,
   dist-info, `direct_url.json`, and the unit file directly. No detection helper
   invokes pip, pipx, or systemctl.
2. **Do not infer pipx ownership from PATH.** The running environment is the
   interpreter (`sys.prefix`), while the executable symlink is reported
   separately. pipx installations are enumerated independently.
3. **Use PEP 610 as the primary cross-venv provenance interface.** pipx metadata
   is preferred where present; `direct_url.json` supplies VCS commit IDs,
   editable/local/artifact distinctions.
4. **Never claim `current` without a SHA.** PyPI-only versions or unknown
   provenance are reported as `unknown` rather than being called current.
5. **A dedicated service venv is not a pipx install.** Its upgrade command uses
   that venv's own Python and always retains the `[api]` extra.
6. **A local wheel is not a local repository.** For artifact installs the output
   states that `direct_url.json` does not record the upstream repository and
   offers a conditional, SHA-pinned Git reinstall rather than reusing the stale
   wheel.
7. **Restart only under clear evidence, and only by the user.** Upgrading an
   unrelated pipx `ref-cli` requires no `ref-api` restart. A restart command is
   printed only when the installed ref-api package is current but `/health`
   reports a stale running revision/version; the command is never executed.
8. **Unknown runtime is not current.** An unreachable or unreadable `/health`
   endpoint, a missing version, or an uninspectable install yields runtime
   `unknown` and an unresolved status. This prevents a false "Nothing to do".
9. **SHA difference is not a downgrade signal.** Only GitHub compare evidence
   classifies `behind`/`ahead`/`diverged`; local mismatch alone is `different`,
   and unresolved evidence is `unknown`.
10. **Task lifecycle.** Tasks live under `.codex/tasks/wip/` while active, move to
    `.codex/tasks/review/` with State `REVIEW` for review, and to
    `.codex/tasks/done/` only after acceptance. This record is in `review/`.

## Read-only production topology check (minion-26)

Ran the new reporter from the development venv with explicit read-only paths; it
did not call pip/pipx/systemctl and made no changes:

```text
ref-cli
  Executable: /home/draeician/.local/bin/ref
  Resolved executable: /home/draeician/.local/share/ref-services/ref-api/bin/ref
  Environment: /home/draeician/.local/share/ref-services/ref-api
  Installation: dedicated virtualenv (local artifact)
  Installed revision: 80c6e3791
  Latest GitHub revision (main): 80c6e379106a73c047cd517e56207bc62d558d7f
  Status: current

pipx ref-cli (/home/draeician/.local/share/pipx/venvs/ref-cli)
  Installation: pipx (git); source git+https://github.com/draeician/ref
  Installed revision: 80c6e3791
  Status: current

ref-api
  ExecStart: .../ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000
  Same environment as ref-cli: yes
  Installed revision: 80c6e3791
  Running API endpoint: http://127.0.0.1:8000/health
  Running API version: 1.6.12b1.dev129+g80c6e3791
  Running API revision: 80c6e3791
  Runtime status: current - running revision matches the installed package
  Status: current

Nothing to do: all detected installations are current.
```

## Verification (all actually run)

Environment: `/tmp/opencode/ref-venv` (Python 3.14.4, editable install with
`.[api,test]`, plus local-only `ruff`/`build`). No global package installs.

| Command | Exit | Result |
|---|---:|---|
| `/tmp/opencode/ref-venv/bin/python -m pytest -q` | 0 | **576 passed, 1 warning in 13.64s** |
| `... -m pytest -q tests/test_upgrade.py` | 0 | **47 passed in 1.35s** |
| `... -m pytest -q tests/test_upgrade.py tests/test_cli_api_routing.py tests/test_url_dump_api_cli.py tests/test_server_install.py` | 0 | **84 passed, 1 warning in 2.20s** |
| `/tmp/opencode/ref-venv/bin/ruff check --select F,E9,ISC src/ref_cli/upgrade.py tests/test_upgrade.py` | 0 | All checks passed |
| `/tmp/opencode/ref-venv/bin/python -m compileall -q src get_transcript.py` | 0 | Clean |
| `/tmp/opencode/ref-venv/bin/python -c "import ref_cli.cli, ref_cli.upgrade, ref_api.server"` | 0 | Imports OK |
| `/tmp/opencode/ref-venv/bin/python -m build --outdir /tmp/opencode/ref-dist` | 0 | Built wheel + sdist (dev133+g234b6747f) |
| isolated smoke: fresh venv + wheel with `[api]` | 0 | Installed; `ref --version` exit 0 |
| isolated smoke: `HOME=<fresh> ... ref --upgrade` | 0 | Exit 0; **0 files created in fresh HOME**; ahead status, no downgrade |
| `git diff --check` | 0 | Clean |
| secret scan of changed files | 0 | Only `--host`/`--port` token names and env-var names; no credentials |

Real read-only checks (no mutation, no restart):

| Check | Result |
|---|---|
| `ref --upgrade` report against minion-26 topology | installed/running/GitHub all `80c6e3791`; runtime `current` |
| `resolve_revision_relationship("5b23a05", GitHubState)` | `behind` (1 commit) |
| `resolve_revision_relationship("39d7b3510", ...)` | `ahead` (1 commit); no downgrade |
| `resolve_revision_relationship("234b6747f", ...)` | `ahead` (4 commits); no downgrade |

No repository-configured ruff/flake8/mypy gate exists in `pyproject.toml` or
`setup.cfg`. A full default ruff run reports pre-existing legacy `cli.py` issues
(unused imports, f-strings, a Python 3.8 walrus expression) unrelated to this
change; the targeted changed-file safety checks pass.

## Failed checks and limitations

- No failed required check.
- GitHub relationship classification requires a resolvable SHA. A PyPI-only
  install with no `+g<sha>` and no `direct_url.json` is reported `unknown`, not
  `current`; abbreviated SHAs that GitHub cannot resolve are also `unknown`.
- The `/health` endpoint must expose a version containing `+g<sha>` (or a matching
  package version) to classify running state. Missing, non-JSON, timed-out, or
  unreachable endpoints are `unknown`, never `current`; no restart is inferred.
- A locally built wheel records its artifact path, not its source repository. The
  output states that limitation and only offers a conditional SHA-pinned Git
  reinstall.
- Editable installs are compared by recorded revision; uncommitted working-tree
  changes are explicitly not compared.
- The reporter makes public GitHub metadata/commit/compare requests and one local
  `/health` request; network failure, rate-limit, or timeout degrade to `unknown`.
- No production restart or deployment was performed. CI is triggered by a draft
  PR because branch pushes alone did not run the workflow.

## Exactly one next step

Reviewer inspects the draft PR against `main` for branch
`fix/upgrade-instructions-detection`, the task record in
`.codex/tasks/review/`, HANDOFF.md, diff, exact-head CI, and tests; then authorizes
or declines a separately scoped merge/deployment. Do not merge the draft PR or run
`ref --upgrade` from the old production binary until this branch is reviewed and
deployed, because the old implementation mutates the installation.
