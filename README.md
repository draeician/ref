# ref-cli

A command-line tool for recording and managing URL references, with special support for YouTube videos and playlists.

## Installation

```bash
pipx install ref-cli
```

## Configuration

Configuration is stored in `~/.config/ref/config.yaml`. The default configuration includes paths and removable URL parameters. You can customize:

### Skip Patterns

You can configure URLs to skip during processing by adding `skip_patterns` to your config file. This supports both exact matches and glob patterns (using `*` wildcard).

Example configuration:

```yaml
skip_patterns:
  - https://mail.google.com/*  # Skip all Gmail URLs (glob pattern)
  - https://mail.google.com/mail/u/0  # Skip specific URL (exact match)
```

Patterns are checked before processing each URL. Matching URLs will be skipped with an informative message.

## Usage

### Interactive Mode

Run `ref` without arguments to enter interactive mode. You can:

- Enter a single URL or YouTube video ID
- **Paste multiple URLs at once** (one per line) - all URLs will be processed sequentially
- URLs matching skip patterns will be automatically skipped

### File Processing

Process URLs from a file:

```bash
ref --file urls.txt
```

URLs in the file that match skip patterns will be skipped and commented out in the file.

### Title extraction

General pages are fetched with `lynx` and parsed for `<title>`, Open Graph, Twitter meta tags, or an `h1`. Some hosts need extra handling:

- **X / Twitter** (`x.com`, `twitter.com`): prefer `og:title` / `twitter:title`, strip branding suffixes, reject noscript and profile-card placeholders (for example `Name (@handle) on X`), then fall back to the `publish.twitter.com` oEmbed API.
- **Reddit** (`reddit.com`, `redd.it`): reject bot-challenge titles such as `Please wait for verification`, then fall back to the Reddit oEmbed API.
- **Rumble**: prefer `og:title`, then `h1`.

X and Reddit oEmbed responses are cached under `transcripts/ombed` (created on first use). Cached URLs are never re-fetched. Live oEmbed calls share a 10 requests/minute limit and use a browser `User-Agent`; HTTP 429 responses are handled without attempting JSON parse.

### Other Options

- `ref <url>` - Process a single URL
- `ref --file <file>` - Process URLs from a file
- `ref --search <term>` - Search across all fields
- `ref --transcript <url>` - Update transcript for a YouTube video

