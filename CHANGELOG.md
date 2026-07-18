# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `ref-enrich --rate N`: sliding-window throttle for live network fetches (default **30/min**; `0` = unlimited). Cache reuse does not count (`src/ref_cli/enrich_cli.py`, `RateLimiter` in `enrichment.py`)
- `ref-enrich` positional YouTube URL/video IDs for single-target enrich
- Firefox/LibreWolf extension package: `./scripts/build-firefox.sh` → `dist/ref-copy-tab-urls-firefox-v*.xpi`; install notes in `extension/LIBREWOLF-INSTALL.md`

### Changed
- On enrich, private/unavailable YouTube videos: **remove** reference rows without a usable transcript; **keep** rows that have a transcript and stamp `@meta|…|unavailable` plus a stub card under `enrichment/youtube/videos/` so they are not re-fetched
- Extension manifest **v1.1.0** with `browser_specific_settings.gecko` for Firefox/LibreWolf

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