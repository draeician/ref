# [feat] `ref --url-dump DOMAIN` + `GET /urls?domain=` read-only domain URL dump

- Task ID: 3c9a71d4
- State: **[REVIEW-REQUEST]** IMPLEMENTED on branch `feat/url-dump-domain`; full repository gate and focused live-server integration checks passed; **awaiting review before any merge/deploy/cleanup**. No GitHub issue was pre-created for this feature (none exists in the repo tracker); no PR opened yet.
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

## Exactly one next step

Reviewer: review branch `feat/url-dump-domain` commits. Do **not** merge, deploy, or clean up until separately authorized.
