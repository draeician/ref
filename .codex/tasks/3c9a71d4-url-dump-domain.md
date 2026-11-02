# [feat] `ref --url-dump DOMAIN` + `GET /urls?domain=` read-only domain URL dump

- Task ID: 3c9a71d4
- State: **[REVIEW-REQUEST]** IMPLEMENTED on branch `feat/url-dump-domain`, plus the hostname-parsing correction commit `3e947116cf374dd9912856e2d29dc65bea24b2a3`; full repository gate and focused live-server integration checks passed; **awaiting review before any merge/deploy/cleanup**. No GitHub issue was pre-created for this feature (none exists in the repo tracker); no PR opened yet.
- Repository: https://github.com/draeician/ref
- Branch: `feat/url-dump-domain` (created from clean `main` = `origin/main` = `5565ab59da3179841f8caddc0a54e30df5c1b8ce`)
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

Reviewer: review branch `feat/url-dump-domain` commits. Do **not** merge, deploy, or clean up until separately authorized.
