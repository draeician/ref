# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Structured primary capture** in `POST /urls`: `primary.status`, authoritative stored `canonical_url`, `archive_confirmed`, plus a separate `discovery` status. Status is recorded at the archive write/exact existing-row check, never inferred from stdout; existing PDFs and playlists now report `exists` even with no primary stdout.
- **`GET /urls/exists?url=URL`** read-only exact archive lookup (`exists`, `canonical`, `absent`, `unknown`, `error`) using the existing parser and archive lock. Original→stored identity is persisted at `<references>/ref_api_state/url_identities.json`. Responses include `deletion_safe`, true only for proven presence; absence/unknown/error must be treated fail-closed by deletion workflows.
- **`GET /capabilities`** with explicit `api_contract_version: "2"` and feature flags; `/health` also reports the contract version.
- **Optional `Idempotency-Key`** on `POST /urls` with durable request state, 409 on payload reuse, `Idempotent-Replayed`, concurrent per-key serialization, and read-only `GET /requests/{key}` reconciliation. Results remain positionally bound to inputs (`null` = not yet durably confirmed).
- **Forced-request crash recovery**: each input's pre-work archive fingerprint is persisted before a forced write. An interrupted forced attempt whose archive changed is marked `ambiguous` and retried keys fail closed with `409` instead of risking a duplicate forced row; provably unchanged attempts resume safely.
- **`GET /queue/rollback-safety`** and `ref-api --rollback-check`: read-only downgrade guard. Pending/running Reddit discovery jobs (or a corrupt queue) block downgrade, because an older ref-api would consume them as no-op YouTube jobs. Nothing is deleted, rewritten, or migrated; terminal `failed` jobs are preserved.
- **Asynchronous Reddit discovery** through the durable show-notes queue: submission destinations, body links, comment links and short-link canonical URLs are discovered by the worker, with bounded fan-out, independent child retries, loop prevention, and discovered playlists kept link-only.
- Regression coverage for capture paths, exact lookup/deletion safety, idempotency/concurrency/restart recovery including six injection points × `force` true/false, transactional write/fsync/replace failures, downgrade safety, credential redaction, primary isolation from discovery/playlist-child failures, slow/failing discovery, queue enqueue failure, legacy queue snapshots, and a real-route/archive/fixture-HTTP integration test.

### Changed
- `POST /urls` `url` is now the URL actually stored in the archive (after redirect/tracking normalization); `input` remains the original request identity. Existing response fields and CLI rendering are unchanged.
- Reddit discovery no longer runs synchronously or recursively inside the API capture request.
- The queue, identity and idempotency stores now mutate copy-on-write: the new table is written and `fsync`-ed to a temp file, atomically replaced, and only then published in memory. A failure at dump/fsync/replace leaves no phantom accepted state and cannot overwrite a corrupt file.

### Fixed
- A confirmed primary capture is no longer downgraded to `error` when later auxiliary work fails (discovery enqueue, identity bookkeeping, playlist-child expansion, or formatting). The response keeps the authoritative `primary`, and the auxiliary failure is reported separately.
- Exact lookup `absent`/`unknown` is documented and returned as non-proof of absence; `deletion_safe` prevents callers from treating an unresolved canonical reference as never captured.
- `lynx` title fetch now uses an argv list instead of a shell wrapper, so a timeout cannot leave an orphaned shell/lynx process.
- The generic `Error: An unexpected error occurred.` path preserves a sanitized actionable reason (credential-redacted, bounded) for API errors and background job records instead of discarding it. Logs and returned errors redact URL userinfo and token-bearing query/fragment values.

### Infrastructure
- New durable state files beside the archive (`ref_api_state/url_identities.json`, `ref_api_state/idempotency.json`) with atomic writes and fail-closed loading. No show-notes queue migration.
- Next release target: **1.7.0** (new backward-compatible API capabilities). Release publishing and tagging are not part of this change.

- **`ref-api`** optional HTTP server (`pip install 'ref-cli[api]'`): `POST /urls`, `GET /search`, `POST /backup`, `POST /transcript`, `GET /health`
- **`ref --install-server`** / **`--uninstall-server`** / **`--server-status`**: user systemd unit, pipx `[api]` inject, documented `~/.config/ref/config.yaml` template bootstrap
- **Client mode**: `api_url` in config (or `REF_API_URL`) routes `ref <url>`, search, `--file`, `--backup`, and `--transcript` through ref-api
- `ref-enrich --rate N`: sliding-window throttle for live network fetches (default **30/min**; `0` = unlimited). Cache reuse does not count (`src/ref_cli/enrich_cli.py`, `RateLimiter` in `enrichment.py`)
- `ref-enrich` positional YouTube URL/video IDs for single-target enrich
- Firefox/LibreWolf extension package: `./scripts/build-firefox.sh` → `dist/ref-copy-tab-urls-firefox-v*.xpi`; install notes in `extension/LIBREWOLF-INSTALL.md`
- Queue-first transcript fallback via `local_transcribe.queue_api.enqueue_youtube_safe` (origin `ref`, priority 20); distinct user messages for newly enqueued, already-in-queue, and `transcript-pending.md` fallback (`docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`)
- If the Python package isn't importable, `ref` shells out to `lt queue add` when `lt` is on `PATH`; if neither is available, silently records the URL in `transcript-pending.md`

### Fixed
- Rumble capture no longer aborts when `yt-dlp` is missing from `PATH`: resolve via PATH, the pipx/venv sibling binary, or `python -m yt_dlp`, and still record the reference with `No transcript available` on failure (`src/ref_cli/cli.py`)
- Rumble rows now store channel as uploader and `Rumble` as source (`|{channel}|Rumble|{status}`), scraping `.media-heading-name` from the page via lynx
- `ref --backup` on the archive host (loopback / local `api_url`) uses a local file copy instead of HTTP self-download; API backup downloads write via a `.partial` temp file so they cannot truncate the file being streamed (`src/ref_cli/cli.py`, `src/ref_cli/api_client.py`)

### Changed
- `get_transcript.py`: compatible with `youtube-transcript-api` 1.2.0+ `FetchedTranscript`/`FetchedTranscriptSnippet` objects while still reading legacy dict segments; duration rounded (not truncated) to the nearest second; `get_video_metadata` returns a stable `id`/`title`/`channel`/`published_at` schema on every path
- On enrich, private/unavailable YouTube videos: **remove** reference rows without a usable transcript; **keep** rows that have a transcript and stamp `@meta|…|unavailable` plus a stub card under `enrichment/youtube/videos/` so they are not re-fetched
- Extension manifest **v1.1.0** with `browser_specific_settings.gecko` for Firefox/LibreWolf
- Blocked / no-caption YouTube failures no longer always claim “queued in transcript-pending.md”; messaging follows local-transcribe enqueue outcomes (requires `pipx inject ref-cli local-transcribe`)

## [1.6.11] - 2026-07-17

### Added
- `ref-advisors`: scan `references.md` and rank trusted advisors (YouTube channels, X handles, web/blog authors) by save frequency; markdown/json/csv output; `--role` / `--exclude-role` (`src/ref_cli/advisors.py`)
- Shell tab completion via `argcomplete` for `ref`, `ref-advisors`, `ref-enrich`, and title-repair CLIs (`src/ref_cli/completion.py`)
- Versioned `references.md` header (`# ref-references version=2`) with layered auto-migrate 1→2→… (`src/ref_cli/references_format.py`)
- Hybrid enrichment: `@meta|category|role|channel_id` on rows + meta cards under `enrichment/youtube/videos|channels/*.json`; `ref-enrich` batch CLI (default limit 50) (`src/ref_cli/enrichment.py`, `src/ref_cli/enrich_cli.py`)
- Capture-time YouTube enrichment on `ref` save (best-effort card + `@meta` stamp)
- Gzip backups by default for `ref --backup` and format migrate; `--nocompress` for plain copies (`src/ref_cli/backup_util.py`)

## [1.6.10] - 2026-07-10

### Added
- Cache X and Reddit oEmbed JSON under `transcripts/ombed` (create on demand); skip the network when a cache file exists, cap live oEmbed calls at 10/minute, use a browser User-Agent, and treat HTTP 429 as a soft failure without JSON-decoding HTML error pages (`src/ref_cli/cli.py`)
- `ref-fix-x-titles` and `ref-fix-reddit-titles`: scan `references.md`, re-fetch titles, and rewrite only the title field in place on mismatch (dry-run by default; `--apply` / `--limit` / `--file`) (`src/ref_cli/title_fixer.py`, `src/ref_cli/fix_x_titles.py`, `src/ref_cli/fix_reddit_titles.py`)
- `ref --help` epilog pointing at the title-repair helper scripts

## [1.6.9] - 2026-07-10

### Fixed
- Reddit title capture: reject bot-challenge interstitial titles (`Reddit - Please wait for verification`) and fall back to `https://www.reddit.com/oembed` (including `redd.it` short links) so post titles are recorded correctly (`src/ref_cli/cli.py`)
- X/Twitter title capture: reject generic profile-card `og:title` / `twitter:title` values such as `Name (@handle) on X`, then use a quoted `<title>` when present or the `publish.twitter.com` oEmbed API so status URLs record the post text instead of the profile label (`src/ref_cli/cli.py`)

## [1.6.8] - 2026-05-13

### Fixed
- Rumble transcript log noise: expected `yt-dlp` failures (HTTP 403 / Forbidden, "Unable to download webpage", "did not produce subtitle files") are now logged at `WARNING` with raw stderr at `DEBUG`, instead of `ERROR:root`, so successful Rumble reference capture no longer prints alarming error lines (`src/ref_cli/cli.py`)
- Unexpected `yt-dlp --dump-json` failures for Rumble continue to log at `ERROR` so genuine problems remain visible

## [1.6.7] - 2026-05-13

### Fixed
- X/Twitter title capture: prefer `og:title`/`twitter:title` over the generic `<title>` tag, strip ` / X` and ` | X` branding suffixes, and reject `X` placeholders so x.com and twitter.com URLs record the real post title (`src/ref_cli/cli.py`)
- Detect X's `JavaScript is not available.` no-JS shell text and fall back to the `publish.twitter.com` oEmbed API for both `title` and blockquote HTML when the static page returns the placeholder
- Improve Rumble transcript fetching with browser-style headers and cookie support, and surface cleaner error messages on failure
- Remove explicit `urllib3` / `chardet` / `charset-normalizer` dependency pins that triggered `RequestsDependencyWarning`
- Fix variable shadowing bug in `read_urls_from_file` that could mask the outer URL when processing files

## [1.6.6] - 2026-02-15

### Fixed
- YouTube transcript `FetchedTranscriptSnippet` error: replaced `segment.get()` calls with dictionary-style access to fix `AttributeError` when processing YouTube transcripts

## [1.6.5] - 2026-01-20

### Changed
- Post-merge updates and housekeeping following the URL skip patterns / multi-URL paste merge

## [1.6.4] - 2026-01-12

### Added
- URL skip patterns configuration in `~/.config/ref/config.yaml`
- Support for exact URL matches and glob patterns (using `*` wildcard) in skip patterns
- Multi-URL paste functionality in interactive mode - paste multiple URLs at once (one per line)
- Automatic skip pattern checking in both interactive mode and file processing mode
- Informative messages when URLs are skipped due to skip patterns

### Changed
- Interactive mode now accepts multi-line input for batch URL processing
- File processing mode now skips URLs matching skip patterns and comments them out

### Fixed
- Updated YouTubeTranscriptApi usage for v1.2.3+ compatibility (replaced deprecated class methods with instance methods)

## [1.6.3] - 2025-11-07

### Added
- YouTube transcript API throttling detection and pending queue system
- Automatic addition of blocked URLs to `transcript-pending.md` for later processing
- Duplicate prevention when adding URLs to the pending file
- Simplified user-friendly message for blocked transcripts in references.md

### Changed
- Updated blocked transcript error message to show "Transcript unavailable (queued in transcript-pending.md)" instead of long technical details

## [1.6.0] - 2025-04-30

### Added
- Support for fetching transcripts from Rumble videos using yt-dlp
- Improved error handling and logging for transcript fetching
- Support for multiple subtitle file formats (VTT, SRT, etc.)

### Fixed
- Improved error handling for missing lynx dependency
- Fixed title extraction to handle both name and property Twitter meta tags
- Enabled arXiv PDF to article URL translation
- Improved URL deduplication and simplification
- Prevented MSN article URLs from redirecting to homepage

## [1.5.2] - 2025-01-16

### Fixed
- Improved error handling for missing lynx dependency
- Fixed title extraction to handle both name and property Twitter meta tags
- Enabled arXiv PDF to article URL translation
- Improved URL deduplication and simplification

### Added
- Added arXiv PDF to article URL translation feature

## [1.5.1] - 2025-01-01

### Fixed
- Prevented MSN article URLs from redirecting to homepage
- Added temp files to .gitignore

## [1.5.0] - 2024-12-03

### Changed
- Converted ref command to pipx installable package
- Updated project structure and organization
- Improved gitignore for Python package artifacts

### Added
- File-based URL processing with auto-commenting feature

## [1.4.0] - 2024-10-03

### Added
- Improved title extraction using lynx and BeautifulSoup 