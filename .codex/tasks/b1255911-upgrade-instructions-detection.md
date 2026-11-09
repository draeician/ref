# [fix] Make `ref --upgrade` strictly read-only and topology-aware

- **Task ID:** b1255911
- **Owner:** OpenCode
- **State:** IN-REVIEW (repo convention: `.codex/tasks/` has no `wip/`→`review/` subdirectories; this file is the single task record, as noted by task `3c9a71d4`)
- **Branch:** `fix/upgrade-instructions-detection`
- **Baseline:** `origin/main` = `80c6e379106a73c047cd517e56207bc62d558d7f`
- **Implementation commit:** `39d7b3510d6d5da63d31b37fa424ce52d294995f`
- **Evidence commit:** `e5155acc6194bfb2e7090dd51a088f2676b03240`
- **Verified remote head before final record update:** `5e6367a0bc12bdcfacb8f1efdebe3914cba99ad6`
- **Authorization:** implementation, tests, commit, push. **No merge, deployment, production package change, or service restart.**

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

## Implementation summary

`ref --upgrade` now only reads local metadata, the service unit, and public GitHub
metadata, then prints instructions:

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
- Compares full or abbreviated Git SHAs; refuses to claim `current` unless the
  comparison has reliable revision evidence.
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
- `tests/test_upgrade.py` — 37 regression tests, including actual `cli.main()`
  dispatch and no-mutation assertions.
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
7. **Restart only when the service environment changes.** Upgrading an unrelated
   pipx `ref-cli` explicitly does not require a `ref-api` restart.
8. **Task directory convention.** This repo has no `.codex/tasks/wip/` or
   `review/`; `3c9a71d4` documents that convention. The state is encoded in this
   record instead.

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
  Status: current
```

## Verification (all actually run)

Environment: `/tmp/opencode/ref-venv` (Python 3.14.4, editable install with
`.[api,test]`, plus local-only `ruff`/`build`). No global package installs.

| Command | Exit | Result |
|---|---:|---|
| `/tmp/opencode/ref-venv/bin/python -m pytest -q` | 0 | **566 passed, 1 warning in 13.67s** |
| `... -m pytest -q tests/test_upgrade.py tests/test_cli_api_routing.py tests/test_url_dump_api_cli.py tests/test_server_install.py` | 0 | **74 passed, 1 warning in 2.05s** |
| `/tmp/opencode/ref-venv/bin/ruff check --select F,E9,ISC src/ref_cli/upgrade.py tests/test_upgrade.py` | 0 | All checks passed |
| `/tmp/opencode/ref-venv/bin/python -m compileall -q src get_transcript.py` | 0 | Clean |
| `/tmp/opencode/ref-venv/bin/python -c "import ref_cli.cli, ref_cli.upgrade, ref_api.server"` | 0 | Imports OK |
| `/tmp/opencode/ref-venv/bin/python -m build --outdir /tmp/opencode/ref-dist` | 0 | Built wheel and sdist |
| isolated smoke: fresh venv + wheel with `[api]` | 0 | Installed; `ref --version` exit 0 |
| isolated smoke: `HOME=<fresh> ... ref --upgrade` | 0 | Exit 0; **0 files created in fresh HOME** |
| `git diff --check` | 0 | Clean |
| secret scan of changed files | 0 | Only non-secret env-var names (`YOUTUBE_API_KEY`, etc.); no credentials |

No repository-configured ruff/flake8/mypy gate exists in `pyproject.toml` or
`setup.cfg`. A full default ruff run reports pre-existing legacy `cli.py` issues
(unused imports, f-strings, a Python 3.8 walrus expression) unrelated to this
change; the targeted changed-file safety checks pass.

## Failed checks and limitations

- No failed required check.
- GitHub comparisons require a SHA. A PyPI-only install with no `+g<sha>` and no
  `direct_url.json` is reported `unknown`, not `current`.
- A locally built wheel records its artifact path, not its source repository. The
  output states that limitation and only offers a conditional SHA-pinned Git
  reinstall.
- Editable installs are compared by recorded revision; uncommitted working-tree
  changes are explicitly not compared.
- The reporter still makes one public GitHub metadata request and one commit
  request; network failure/rate-limit/timeout degrade to `unknown`.
- No production restart or deployment was performed.

## Exactly one next step

Reviewer inspects pushed branch `fix/upgrade-instructions-detection`, task record,
HANDOFF.md, diff, and tests; then authorizes or declines a separately scoped
merge/deployment. Do not run `ref --upgrade` from the old production binary until
this branch is reviewed and deployed, because the old implementation mutates the
installation.
