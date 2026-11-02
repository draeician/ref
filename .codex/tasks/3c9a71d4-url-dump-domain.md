# [feat] `ref --url-dump DOMAIN` + `GET /urls?domain=` read-only domain URL dump

- Task ID: 3c9a71d4
- State: **[DONE]** MERGED. PR #26 (https://github.com/draeician/ref/pull/26) was merged into `main` as merge commit
  `dd15d8ad444a91c2f5d81175bdf435c64395c6db` at `2026-11-02T05:30:23Z`; the reviewed head `b4ad674af5e2f2bc45322067eb8c7a5b620d7633`
  and all eight feature/test/docs commits are reachable from `origin/main`, CI is green on that merge commit, and the local +
  remote feature branches have been cleaned up (see "[DONE] Merge and branch cleanup" below). **Deployment was not authorized: no
  package installed or upgraded and no service restarted on `minion-26`.** No GitHub issue was pre-created for this feature (none
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

## Post-merge documentation record

Direct commits to `main` are prohibited, so these post-merge records are delivered from branch
`docs/record-url-dump-merge-cleanup` (branched at merged main `dd15d8a…`) through a separate **documentation-only PR**, which is
left open for review and **not** merged without authorization. Documentation only: no code, tests, or archive data changed; the
local gate re-run on this branch is unchanged (**542 passed, 1 warning**).

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

Authorize the **deployment** decision only: install the merged code (`main` @ `dd15d8ad444a91c2f5d81175bdf435c64395c6db`) on
`minion-26`, restart `ref-api`, and smoke-test `ref --url-dump DOMAIN` against the live API. Deployment was **not** authorized in
the merge/cleanup task, so nothing has been installed, upgraded, or restarted; do not do it until separately authorized.
