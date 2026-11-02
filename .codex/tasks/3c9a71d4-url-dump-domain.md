# [feat] `ref --url-dump DOMAIN` + `GET /urls?domain=` read-only domain URL dump

- Task ID: 3c9a71d4
- State: **[DONE]** MERGED **and DEPLOYED**. PR #26 (https://github.com/draeician/ref/pull/26) was merged into `main` as merge commit
  `dd15d8ad444a91c2f5d81175bdf435c64395c6db` at `2026-11-02T05:30:23Z`; the reviewed head `b4ad674af5e2f2bc45322067eb8c7a5b620d7633`
  and all eight feature/test/docs commits are reachable from `origin/main`, CI is green on that merge commit, and the local +
  remote feature branches have been cleaned up (see "[DONE] Merge and branch cleanup" below). Production deployment on
  `minion-26` was then **authorized and completed** from approved source `main @ 80c6e379106a73c047cd517e56207bc62d558d7f`: both the
  pipx CLI environment and the dedicated `ref-api` service environment now run `ref-cli 1.6.12b1.dev129+g80c6e3791`, all eleven
  production acceptance checks passed, and archive/queue/backlog data are intact (see "[DONE] Production deployment on minion-26").
  No GitHub issue was pre-created for this feature (none
  exists in the repo tracker). Because direct commits to `main` are prohibited, these post-merge records arrive through a separate
  documentation-only PR — see "Post-merge documentation record".
- Repository: https://github.com/draeician/ref
- Branch: `feat/url-dump-domain` (created from clean `main` = `origin/main` = `5565ab59da3179841f8caddc0a54e30df5c1b8ce`; merged as
  `dd15d8ad444a91c2f5d81175bdf435c64395c6db`, then deleted locally and on the remote — see "[DONE] Merge and branch cleanup")
- Task convention note: this repo uses `.codex/tasks/` with hash prefixes (no `wip/`→`review/` directories; those exist only in sibling repos' `.crules/tasks/`). This file is the single task record, marked ready-for-review.

## [CLAIM] Deliverable

Read-only dump of every stored URL whose **parsed hostname** equals a domain or is a subdomain of it (case-insensitive), one raw URL per stdout line, newest first:

- CLI: `ref --url-dump DOMAIN` → thin client over the remote ref-api (`api_url` / `REF_API_URL` required; no local archive involved).
- API: `GET /urls?domain=DOMAIN` reusing the existing `ListResponse` schema and `iter_data_rows` parser.

## Scope implemented (additive only, 149 diff lines)

- `src/ref_cli/domain_match.py` (new): `normalize_domain`, `url_hostname`, `hostname_matches`.
- `src/ref_api/listing.py`: `list_urls_by_domain` — server-side filter + stable newest-first sort on `row.timestamp`; missing archive → `[]`.
- `src/ref_api/service.py`: `list_urls_for_domain` (uses `ref_cli.UNIFIED`).
- `src/ref_api/routes.py`: `GET /urls` route `dump_urls_by_domain`; blank domain → 400, invalid domain → 400 (`ValueError` mapped), missing parameter → FastAPI 422.
- `src/ref_cli/api_client.py`: `urls_for_domain`, `url_dump_via_api` (errors on **stderr** only; exit 1).
- `src/ref_cli/cli.py`: `--url-dump DOMAIN` flag + epilog line, `run_url_dump()`, dispatched in `main()` **before** `ensure_path_exists(UNIFIED)` / `ensure_references_migrated(...)` so no archive bootstrap or migration ever runs for this flag.
- `README.md`: curl example, API-client bullet, "Other Options" entry.

Matching is label-anchored on the parsed hostname (never substring): `example.com`, `www.example.com`, `docs.example.com` match; `notexample.com`, `example.co`, `example.com.evil.net` do not. URL strings are returned exactly as stored (paths, query strings with spaces/unicode, fragments intact). Duplicates preserved. No new dependencies; no unrelated refactors; existing `POST /urls`, `GET /list`, `/search` semantics untouched.

## [REVIEW-REQUEST] Correction — `url_hostname()` authority parsing (commit `3e947116cf374dd9912856e2d29dc65bea24b2a3`)

**Defect found while continuing ownership of this branch.** The first implementation decided
authority parsing with `if '//' not in text`, i.e. anywhere in the stored value, and fell back to
synthesizing a `//` authority for anything without slashes:

| Stored value | Before | Required |
|---|---|---|
| `example.com/path?q=https://other.com` | no host → **not dumped** by `--url-dump example.com` | matches `example.com` (and never `other.com`) |
| `example.com/foo//bar` | no host → **not dumped** | matches `example.com` |
| `mailto:user@example.com` | host `example.com` → **dumped** | not a web hostname |
| `user@example.com` | host `example.com` (userinfo of the synthesized authority) → **dumped** | not a web hostname |

**Fix (`src/ref_cli/domain_match.py`, no other module touched).** Only a leading `scheme://` or a
leading `//` marks a hierarchical URL; `//` appearing later stays inside the path/query and cannot
suppress authority parsing. A scheme token that is followed by neither slashes nor a dotted host
(`mailto:`, `tel:`, `urn:` …) plus an explicit non-web deny-list (`about`, `blob`, `data`,
`javascript`, `mailto`, `magnet`, `sms`, `tel`, `urn`) returns `None`. A value with no scheme of its
own whose authority contains `@` is treated as an email address, not a stored URL. Preserved:
normal HTTPS/HTTP matching, userinfo on real URLs (`https://user:pw@sub.example.com:8443/p?q=1`),
scheme-less authorities including host:port (`example.com:8443/path`, `//example.com/x`,
`[::1]:8000/x`), trailing-dot and case normalization, label-anchored subdomain rule, exact stored
URL output, and every existing `normalize_domain` / route / CLI error behavior.

**New regression tests (23 cases).** `tests/test_url_dump_matching.py`: the four required cases,
embedded-`//` host extraction (`example.com/a#https://other.com/b`, scheme-relative with a URL in
the query), opaque-scheme and email rejection (`mailto:`/`MAILTO:`, `tel:`, `data:`, `urn:`,
`magnet:`, `user@example.com/reset`), legitimate-authority preservation (userinfo URLs, scheme-less
host:port with embedded slashes), plus two archive-level checks on
`list_urls_by_domain` — the exact newest-first dump of a scheme-less edge archive and an empty dump
for `other.com`. `tests/test_url_dump_api_cli.py`: one `GET /urls?domain=example.com` route case over a
seeded archive containing all four values.

**Verification commands actually run (same env as before, CPython 3.12.15 at
`/tmp/opencode/ref-url-dump-venv`, editable install of `".[api,test]"`).**

1. Focused: `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest tests/test_url_dump_matching.py tests/test_url_dump_api_cli.py -q` → **92 passed, 1 warning in 1.59s** (69 previous + 23 new).
2. Full repository gate (exact CI command): `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` → **542 passed, 1 warning in 13.36s** (the same single pre-existing `StarletteDeprecationWarning`). No test was skipped, xfailed, or weakened.
3. Read-only live-server smoke re-run (`/tmp/opencode/url-dump-smoke-fix`, uvicorn `--factory 'ref_api.app:create_app'` on 127.0.0.1:8765 with an isolated server HOME and a freshly seeded archive; script `run_checks.sh`, log `checks.log`):
   - `curl "http://127.0.0.1:8765/urls?domain=example.com"` → `["https://docs.example.com/guide/a_b#c", "example.com/path?q=https://other.com", "sub.example.com/foo//bar?q=1#frag", "https://www.example.com/search?q=hello world&x=1#üñîçødé", "example.com/oldest?keep=1"]` — newest first, exact stored strings, scheme-less embedded-`//` rows now included, `mailto:`/email rows and the `notexample.com` / `example.com.evil.net` decoys excluded.
   - `curl "…/urls?domain=sub.example.com"` → only `sub.example.com/foo//bar?q=1#frag`; `curl "…/urls?domain=other.com"` → `{"urls":[]}` (a host embedded in another host's query is never dumped).
   - Invalid domain → **400** with the original detail text; blank domain → **400**.
   - `ref --url-dump Example.COM` (isolated HOME + `REF_API_URL`) → exit 0, five pure URL lines on stdout, stderr 0 bytes, zero ANSI codes; `--url-dump sub.example.com` → the one expected line.
   - Existing CLI error behavior unchanged: no matches → exit 0 with both streams empty; unreachable API (`:8799`) → exit 1, message only on stderr; malformed domain `com` → exit 1 before any HTTP call; missing `api_url` → exit 1 "requires api_url" on stderr.
   - Read-only proof: smoke archive sha256 `e63590674f03ac39fb41342cb3fccd260fcced949c35a583cefc604867e0fa86` identical before and after every request; real production archive `/home/draeician/references/references.md` sha256 `5c61ea978b58e390cd2f21f7f359f3b4973b21bf844ce7f59c3e45f2a74c7d35` before and after a real-HOME dump run (byte-identical). Server journal: only `/health`, `/urls` 200s and the two expected 400s; no error or traceback lines. The smoke uvicorn process was started by this task and stopped with `SIGTERM`; port 8765 closed, no listener left. No production service was contacted, restarted, or modified.
   - Limitation: the smoke server ran with `REF_TRANSCRIPT_RECONCILE_ENABLED=false` so the periodic reconciler pass could not touch even the temp archive; `/urls` behavior is independent of that setting.
4. Secret scan of the diff and changed files (`api[_-]?key|secret|token|passw|credential|PRIVATE KEY|AKIA…|ghp_…|Bearer …`): only prose matches ("Credentials are honoured…", "``token:``" comment) plus the synthetic test fixtures `https://user:pw@example.com/inbox` and `http://admin:t3st@sub.example.com:8443/p?q=1`. No real secret value present.

## Acceptance evidence (must actually run — results recorded)

Environment: CPython 3.12.15 venv at `/tmp/opencode/ref-url-dump-venv` (`uv venv --python 3.12`; `VIRTUAL_ENV=... uv pip install -e ".[api,test]"`). CI gate is the same command (`.github/workflows/tests.yml`, Python 3.12, `pip install -e ".[api,test]"`, `python -m pytest -q`).

1. **Baseline on unmodified `main`** (`5565ab59`): `python -m pytest -q` → **450 passed, 1 warning in 18.36s**.
2. **Focused feature tests**: `pytest tests/test_url_dump_matching.py tests/test_url_dump_api_cli.py -q` → **69 passed** (exact + subdomain match, false-positive hosts, mixed case both directions, paths/queries/spaces/unicode preserved, empty result exit 0, malformed domain rejection before any HTTP call, API/network failure exits 1 with message only on stderr, stdout purity/no ANSI, route 400s, `POST /urls` + `GET /list` unchanged, read-only sha256 checks at listing/API/CLI layers, `main()` never calls `ensure_path_exists` or `ensure_references_migrated`).
3. **Full repository gate after changes**: `python -m pytest -q` → **519 passed, 1 warning in 13.52s** (450 baseline + 69 new; same single pre-existing StarletteDeprecationWarning).
4. **Live-server integration** (`/tmp/opencode/url-dump-smoke`, uvicorn `--factory ref_api.app:create_app` on 127.0.0.1:8765, isolated server HOME + seeded temp archive; scripts `run_checks.sh` / `run_checks2.sh`):
   - `curl "…/urls?domain=example.com"` → newest-first exact stored strings, decoys excluded; invalid domain and blank domain → **400** with descriptive detail.
   - `ref --url-dump Example.COM` (isolated HOME + `REF_API_URL`) → exit 0, four pure URL lines on stdout, **stderr empty, zero ANSI codes**.
   - No matches → exit 0, stdout and stderr both empty.
   - Unreachable API (`:8799`) → exit 1, stdout empty, friendly message on stderr.
   - Malformed domain `com` → exit 1 before any HTTP call; missing `api_url` → exit 1 with "requires api_url" on **stderr**, stdout empty.
   - Run against the **real** production config (`~/references/references.md`, sha256 recorded before/after) → dump served from temp server, production archive byte-identical; smoke-server archive sha `283835fe…` unchanged across all requests (read-only proven at HTTP layer).
5. `--help` smoke: flag and epilog line render correctly.

## [REVIEW-REQUEST] Pull request and CI evidence (PR #26)

**Preconditions verified before opening.** `git fetch origin --prune`; working tree clean; local HEAD =
`origin/feat/url-dump-domain` = `50bfc2f7fa0baaba2221f9988ae5923c62192dbb` (0 ahead / 0 behind); merge-base with
`origin/main` equals the current main tip `5565ab59da3179841f8caddc0a54e30df5c1b8ce`, so no rebase was needed and
no force-push was used.

**Documentation-only heading correction.** The task-record section for the hostname-parsing fix carried the `[WIP]`
status signal although it is complete and verified; it now reads `[REVIEW-REQUEST]`. Commit `50bfc2f7fa0baaba2221f9988ae5923c62192dbb`
(`[docs] Mark the hostname-parsing correction review-ready`, 1 file, +1/−1), pushed normally to
`feat/url-dump-domain`. No implementation, test, or evidence content changed.

**Pull request.** `gh pr create --repo draeician/ref --base main --head feat/url-dump-domain --title "feat: Add read-only domain URL dump" --body-file …`
→ **https://github.com/draeician/ref/pull/26**. Recorded state after CI finished: state OPEN, base `main` @
`5565ab59`, head `feat/url-dump-domain` @ `50bfc2f7…`, `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`,
11 changed files, +1139/−0, auto-merge not enabled (`autoMergeRequest: null`), no review requests. Body follows the
repo PR convention (linked task path, summary/rationale, test evidence and coverage notes, risks and rollback steps).

**CI verification.** Workflow `tests` (`.github/workflows/tests.yml`, the only workflow in the repository), run id
`41391655727`, event `pull_request`, head SHA `50bfc2f`:

- `gh pr checks 26 --repo draeician/ref --watch --interval 15` → `pytest  pass  31s`.
- Run/job conclusion: **success**; job `pytest` started `2026-11-02T05:01:55Z`, completed `2026-11-02T05:02:26Z`; every step success (Set up job, checkout@v4, setup-python@v5, install `".[api,test]"`, run pytest suite, posts).
- CI log line from the pytest step: **`542 passed, 1 warning in 11.85s`** — identical to the local gate count recorded above.
- `gh pr view 26 --json statusCheckRollup` → single check `pytest`, `status=COMPLETED`, `conclusion=SUCCESS`; run list for the head SHA shows exactly one workflow (`tests`) with conclusion success.

**CI limitations / blockers (recorded honestly, none block review).**

- `main` has **no branch protection configured** (`GET /repos/draeician/ref/branches/main/protection` → 404 "Branch not protected"), so no check is enforced as *required*; "all required checks pass" here means the only CI GitHub reports for this PR (1 of 1, `pytest`) succeeded and `mergeStateStatus=CLEAN`.
- While the run was queued the merge state read `UNSTABLE`; it became `CLEAN` after the check completed. No legacy combined commit status exists (`commit.status` is null; checks-only).
- The Actions log carries an unrelated runner warning that `actions/checkout@v4` and `actions/setup-python@v5` are forced onto Node.js 24 (Node 20 deprecation); it does not affect the test result.
- CI installs Python 3.12 on ubuntu-latest, matching the local verification interpreter; no matrix beyond that single version is configured.
- Every push to this branch re-triggers the same single `tests` workflow, so a later documentation-only commit advances the PR head again. Run `41391655727` above verified head `50bfc2f…`; reviewers should confirm `gh pr checks 26 --repo draeician/ref` is green against the then-current head before any merge.

**Re-verification after the documentation commits.** The review-ready heading correction (`50bfc2f…`) and this evidence
commit (`c88f90d11e4e7c74c4e7b7bf09d72988bdb889e9`, `[docs] Record PR #26 and CI verification evidence`, 2 files, +75/−4)
were each pushed normally to `feat/url-dump-domain` (no force-push). The push of `c88f90d…` produced workflow run
`41392192743` (event `pull_request`, head `c88f90d`) → **conclusion success**, job `pytest` 05:07:41Z → 05:08:14Z, no failed
steps, log line **`542 passed, 1 warning in 12.63s`**; `gh pr checks 26 --watch` reported `pytest pass 33s`, and after it
completed `mergeable=MERGEABLE` with `mergeStateStatus=CLEAN` at head `c88f90d…`. Local gate re-run on the same tree:
542 passed, 1 warning. A documentation-only push after this record will advance the head once more; confirm checks green
at merge time as noted above.

## [DONE] Merge and branch cleanup (2026-11-02, authorized)

Authorization given: **merge + branch cleanup approved; deployment NOT authorized.** Nothing was installed, upgraded, or
restarted on `minion-26`.

**Preflight (all verified before merging).** No `AGENTS.md`/`project_spec.md` at the repository root; the repo guides are
`.codex/AGENTS.md` and `.codex/AGENTS_WORKFLOW.md`, read first. Commands and results:

| Check | Command | Result |
|---|---|---|
| Remote refs refreshed, stale pruned | `git fetch origin --prune` | no new commits on either ref |
| Working tree clean | `git status --short` | empty |
| PR open / mergeable / not draft | `gh pr view 26 … --json state,isDraft,mergeable,mergeStateStatus,headRefOid,baseRefOid,autoMergeRequest` | `state=OPEN`, `isDraft=false`, `mergeable=MERGEABLE`, `mergeStateStatus=CLEAN`, head `b4ad674af5e2f2bc45322067eb8c7a5b620d7633` = reviewed SHA, base `main` @ `5565ab59…`, 8 commits, auto-merge null |
| CI green on that exact head | `gh pr checks 26 --repo draeician/ref`; `gh api …/commits/b4ad674…/check-runs` | one check `pytest pass 41s` (run `41392600076`, job `125107046328`); check-run on head `b4ad674`: `status=completed`, `conclusion=success` |
| No divergence / no conflicts | `git rev-list --left-right --count origin/feat/url-dump-domain...HEAD`; `git merge-base HEAD origin/main` | `0 0`; merge-base `5565ab59…` (main tip) — main had not moved |
| Local gate at the reviewed head | `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` | **542 passed, 1 warning in 13.23s** |

**Merge.** `gh pr merge 26 --repo draeician/ref --merge` → normal merge commit (no squash, no rebase, no force-push):
**merge SHA `dd15d8ad444a91c2f5d81175bdf435c64395c6db`**, subject `Merge pull request #26 from draeician/feat/url-dump-domain`,
committed by GitHub on behalf of `draeician`, merged at **`2026-11-02T05:30:23Z`**.

**Merge verification.**

| Check | Command | Result |
|---|---|---|
| PR state | `gh pr view 26 --json state,mergedAt,mergeCommit,mergedBy` | `state=MERGED`, mergedAt `2026-11-02T05:30:23Z`, mergeCommit `dd15d8a…`, mergedBy `draeician` |
| Two-parent history preserved | `git cat-file -p dd15d8a…` / `git rev-parse dd15d8a^1 dd15d8a^2` | parents `5565ab59…` (previous main tip) and `b4ad674…` (reviewed head) — a real merge commit, not a squash |
| Reviewed commits reachable from main | `git merge-base --is-ancestor <sha> origin/main` for all 8 (`19100a6`, `baba588`, `4240f9b`, `3e947116…`, `58de2f7`, `50bfc2f7…`, `c88f90d1…`, `b4ad674a…`) | all 8 **reachable** |
| Merged tree equals reviewed head | `git diff --stat b4ad674… origin/main` | empty — main content is byte-identical to the reviewed head |
| CI green on main after merge | `gh run list --commit dd15d8a…`; `gh api …/runs/41394410273/jobs`; log grep | workflow `tests`, event **`push`**, conclusion **success**; job `pytest` 05:30:29Z → 05:31:05Z, no failed steps; log line **`542 passed, 1 warning in 12.89s`** |
| Local gate on merged main | `/tmp/opencode/ref-url-dump-venv/bin/python -m pytest -q` (on `main`) | **542 passed, 1 warning in 13.61s** |

**Branch cleanup (only after the merge was verified).**

- `git checkout main` then `git merge --ff-only origin/main` → fast-forward only (`5565ab5..dd15d8a`, no merge commit created locally).
- Local feature branch removed with the safe delete: `git branch -d feat/url-dump-domain` → `Deleted branch feat/url-dump-domain (was b4ad674)` (succeeded because it is fully merged; `-D` was not needed or used).
- Remote branch: GitHub deleted `origin/feat/url-dump-domain` automatically at merge (`git fetch origin --prune` reported `[deleted] (none) -> origin/feat/url-dump-domain`). An explicit `gh api -X DELETE repos/draeician/ref/branches/feat/url-dump-domain` returned **404 Not Found**, confirming it was already gone.
- Stale remote refs pruned by `git fetch origin --prune`. Unrelated branch `origin/fix/youtube-auto-show-notes-api` left untouched; the only worktree (`/opt/md2/git/personal/ref`) and all untracked files were preserved (nothing deleted or cleaned).

**Post-cleanup state.** `HEAD` = `main` = `origin/main` = **`dd15d8ad444a91c2f5d81175bdf435c64395c6db`**, 0 ahead / 0 behind;
`git branch -avv` shows only local `main` plus the unrelated remote branch; `git status --short` empty.

**Roll back (if ever needed).** Revert merge commit `dd15d8a…` (`git revert -m 1 dd15d8ad444a91c2f5d81175bdf435c64395c6db`) —
no migration, schema, config, or archive-data change exists to unwind; `ref --url-dump` and `GET /urls` simply disappear and
every other command/route is unaffected. No production action was taken, so nothing on `minion-26` needs unwinding.

## [DONE] Production deployment on `minion-26` (authorized, 2026-11-02)

Authorization: **deployment approved** from approved source `main @ 80c6e379106a73c047cd517e56207bc62d558d7f` (the PR #27 merge
commit; CI push run `41396641392` success). Scope respected: only the pipx CLI env and the dedicated `ref-api` service env were
touched, plus one graceful restart of `ref-api.service`. Aether, the transcription queue worker, the pending backlog, queue
configuration, and unrelated services/services units were not modified.

**Preflight findings (verified, with two notable discoveries).**

| Check | Command / source | Result |
|---|---|---|
| Approved source + CI | `gh api …/commits/80c6e37…`; runs API for that head | main tip `80c6e37`, parents `dd15d8a`+`5b23a05`, workflow `tests` (push) **success** |
| Actual service unit | `systemctl --user cat/show ref-api.service` | user unit, `ExecStart=/home/draeician/.local/share/ref-services/ref-api/bin/ref-api --host 0.0.0.0 --port 8000`, `EnvironmentFile=-~/.config/ref/ref-api.env`, enabled, active since Oct 28 (PID 1935, NRestarts=0) — **the API does NOT use the pipx env** |
| PATH CLI surprise | `readlink -f ~/.local/bin/ref` | symlink → `ref-services/ref-api/bin/ref` (service venv), not the pipx venv; other `ref-*` shims still point at pipx |
| Service env before deploy | venv python `-VV`; importlib metadata + `direct_url.json` | Python 3.13.17, `ref-cli 1.6.12b1.dev117+g5565ab59d`, wheel-installed from preserved PR #25 backup wheel (`INSTALLER=uv`) |
| pipx env before deploy (out-of-band change found) | dist-info mtimes; full RECORD-vs-git-blob comparison at `80c6e37` | Python 3.14.4, already `dev129+g80c6e3791` installed 13:56Z by an unlogged action (no pipx log); **all 35 package modules byte-identical to the approved source** (only setuptools-scm `_version.py` and bin shims differ), no live install processes — treated as content-equivalent to approved source, then reinstalled from this deploy's audited wheel anyway |
| API health before restart | `curl /health` | `{"status":"ok","version":"1.6.12b1.dev117+g5565ab59d"}` |
| Archive/backlog/queue baseline | stat + sha256 recorded into backup dir | `references.md` 68,298 lines @ sha `74d12955…` (reconciler rewrites it every ~307 s with timestamped `.bak-<UTC>.gz`, so mtime churn is normal); pending backlog sha `d6659db2…`; queue UUID `8c6fc098-8cbe-41ae-9689-dd759797a582` |
| Dependency delta of approved source | `git diff 5565ab59..80c6e37 -- pyproject.toml requirements.txt setup.cfg` | **empty** — safe to install with `--no-deps` |

**Backup (before any change).** Directory `/home/draeician/.local/share/ref-services/deploy-backups/20261102T1416Z-pr26-url-dump/`:
unit + `config.yaml` + `ref-api.env(.template)` copies (mode 0600), service-env package freeze (48 pkgs), old dist-info
`direct_url.json`, **reinstallable copy of the previous wheel** `ref_cli-1.6.12b1.dev117+g5565ab59d-py3-none-any.whl`
(sha256 `d80ee856…`, same bytes as the PR #25 asset), pipx metadata snapshot, archive/backlog stat+hash records, `/health` and
service-state snapshots, journal baseline, queue id/listing, and **`ROLLBACK.md`** with exact commands. Rollback never restores
archive snapshots over newer data — the API's own `.bak-<UTC>.gz` files remain the only archive restore path.

**Install.** Built from `src-ref` checked out at exactly `80c6e37…` (`git describe`: `v1.6.12-beta-129-g80c6e37`) with
`uv build --wheel` → `ref_cli-1.6.12b1.dev129+g80c6e3791-py3-none-any.whl`, sha256 `03ee26870ab8c88de129c01d020d6380ebc3bf682778f9c9d8685f462f0fd7da`
(stored in the backup dir). Installed with `--force-reinstall --no-deps`: service env via `uv pip install --python <service python>`;
pipx env via its own `bin/python -m pip`. Post-install: both envs report `1.6.12b1.dev129+g80c6e3791`; **all 47 non-`ref-cli`
dependencies byte-for-byte identical before/after** (freeze diff); `ref_cli/domain_match.py` present in both; unit file, env file,
queue config, and interpreter choices untouched.

**Restart (idle window).** Reconciler cycle completed at `14:20:00Z` (`updated=4`, backup `.bak-20261102T141959.gz`) and the notes
worker was idle; `systemctl --user restart ref-api.service` issued `14:20:04Z`. Clean uvicorn shutdown/startup in journal, new PID
**3521265**, NRestarts 0, reconciler resumed (`interval=300.0s`) and its first post-restart cycle at 14:20:08 reported
`updated=0 errors=0`. Downtime ≈ 2 s.

**Acceptance checks — all passed.**

| # | Check | Evidence |
|---|---|---|
| 1 | `ref --version` identifies deployed revision | `ref 1.6.12b1.dev129+g80c6e3791`, exit 0 (effective PATH CLI = service-env binary) |
| 2 | `ref --help` shows the flag | usage line + `--url-dump DOMAIN` help entry present |
| 3 | `/health` identifies new version | first poll after restart: `{"status":"ok","version":"1.6.12b1.dev129+g80c6e3791"}`; `ref --status`: `Status: ok (version …dev129…)` exit 0 |
| 4 | `GET /urls?domain=DOMAIN` succeeds | `domain=reddit.com` → HTTP 200, `{"urls":[…]}`, 3,738 URLs; `example.invalid` → 200 `{"urls":[]}` |
| 5 | CLI dump equals API list, one raw URL per line | `ref --url-dump reddit.com`: exit 0, 3,738 stdout lines, empty stderr; **order-identical** to the API array (`identical_ordered=True`) |
| 6 | Domain + subdomain matching correct | `youtube.com` dump = 35,344 URLs across hosts `www.youtube.com` (35,342) + `music.youtube.com` (1) + apex (1); exact-host query `www.youtube.com` returns only that host (35,342, excludes apex/music); `music.youtube.com` output is a strict subset of the apex dump. A naive whole-line grep overcounts (~35,784) because URL tokens also appear inside title/notes fields across field delimiters — the parser reads only stored URL values, which is correct behavior |
| 7 | No matches → empty stdout, exit 0 | `example.invalid`: exit 0, 0 bytes stdout, 0 bytes stderr |
| 8 | API failure → stderr + exit 1 | `REF_API_URL=http://127.0.0.1:8099 ref --url-dump reddit.com` (env override; production config untouched): exit 1, empty stdout, 248-byte stderr "Connection refused…" |
| 9 | Bonus: malformed domain rejected | `ref --url-dump com` → exit 1 with documented message |
| 10 | Production archive intact | all smoke operations read-only (GET + CLI dump only); `references.md` mtime `14:20:00.467Z` predates the restart command (`14:20:04Z`) and post-restart reconciler cycles report `updated=0`; pending backlog sha identical to pre-deploy record (`d6659db2…`); queue listing unchanged (10 entries). Line-count growth vs the early baseline is attributable entirely to scheduled pre-restart reconciler writes, each with its own `.bak-<UTC>.gz` |
| 11 | Existing health/functionality; no new errors | journal since restart shows only clean shutdown/startup + normal cycles; no traceback/error markers beyond routine `/health` 200s and the external `/v1/models` probe 404s that predate the deploy; unit active, NRestarts 0 |

**Rollback readiness.** Full procedure in `ROLLBACK.md` inside the backup dir: reinstall preserved dev117 wheel into either env
with `--force-reinstall --no-deps`, restore unit/config copies if ever needed (they were not changed), restart in an idle window,
verify `/health` reports dev117 — and never overwrite newer archive data. Rollback was **not** required.

## Post-merge documentation record

Direct commits to `main` are prohibited, so these post-merge records were delivered from branch
`docs/record-url-dump-merge-cleanup` (branched at merged main `dd15d8a…`) through the **documentation-only PR
https://github.com/draeician/ref/pull/27** (`[docs] Record url-dump merge and cleanup evidence`; base `main`, 2 files, +133/−6),
which was reviewed under authorization and **merged as `80c6e379106a73c047cd517e56207bc62d558d7f` at `2026-11-02T05:53:37Z`**
(normal merge commit, parents `dd15d8a…` + head `5b23a05…`; post-merge CI push run `41396641392` success) — that merge commit is
the approved source this production deployment installed. Documentation only: no code, tests, README, or archive data changed; the
local gate re-run was unchanged (**542 passed**).

CI for PR #27 at its final head `5b23a0559cd2b0e147b1603474084bb7915a46b2`: workflow `tests` run `41395309762` (event
`pull_request`) → **conclusion success**, job `pytest` 05:39–05:40Z, no failed steps, log line
**`542 passed, 1 warning in 12.95s`**; `gh pr checks 27 --repo draeician/ref --watch` reported `pytest pass 35s`, and afterwards
`mergeable=MERGEABLE` / `mergeStateStatus=CLEAN`. The deployment records above were likewise committed on a dedicated branch
(`docs/record-url-dump-deploy`) and opened as a documentation-only PR for independent review, not merged without authorization.

## Known limits / risks (not claimed fixed)

- Single-label/TLD-only dumps such as `com` are **rejected** by design (documented); IDNs must be supplied in punycode (`xn--…`).
- Labels allow internal `-`/`_` and total length ≤ 253; scheme/path/port/space/`@`/empty labels rejected.
- Newest-first is a stable sort on the stored `timestamp` string (ties keep archive order); it does not re-parse timestamps into datetimes.
- Like other client commands (`--list`, `--status`), config bootstrap may create/merge `~/.config/ref/config.yaml`; the read-only guarantee covers archives and server data, enforced by dispatching before any archive bootstrap/migration.
- No authentication on the new route (same posture as existing routes; `require_auth` placeholder retained).
- After commit `3e947116`: a stored value with **no scheme of its own** whose authority contains `@` is treated as an email address and never dumped (`user@example.com`, `mailto:user@example.com`). Credentials are only honored on values that carry their own hierarchical scheme (`https://user:pw@sub.example.com/`).
- Opaque/non-web schemes (`about`, `blob`, `data`, `javascript`, `mailto`, `magnet`, `sms`, `tel`, `urn`) never produce a hostname. A dotted token before a colon is still read as host:port, so scheme-less `example.com:8443/path` keeps matching; values such as `https:/example.com` (single slash) now resolve to no host instead of the previous garbage host — either way they are not dumped.
- The acceptance counts recorded above for the earlier commits (69 focused / 519 full) were superseded by **92 focused / 542 full** at commit `3e947116`.

## Exactly one next step

Reviewer: independently verify the production deployment on `minion-26` (`ref --version`, `/health`, a read-only
`ref --url-dump DOMAIN` spot check) and authorize merging **this** documentation PR (branch `docs/record-url-dump-deploy`) so the
record lands on `main` — direct commits to `main` are prohibited. No further production action is pending: nothing else was
installed, configured, or restarted, and any future change (including rollback per `ROLLBACK.md` in the deploy backup dir) requires
separate authorization.
