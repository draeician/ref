# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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