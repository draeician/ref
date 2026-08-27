# ref-cli

A command-line tool for recording and managing URL references, with special support for YouTube videos and playlists.

## Installation

```bash
pipx install ref-cli
```

### Local transcription queue (optional)

When YouTube captions are unavailable, `ref` records the URL in
`transcript-pending.md` (the GPU worker can auto-import that file into the
durable queue). If [local-transcribe](https://github.com/draeician/local_transcribe)
(≥ 0.5.0) is available, `ref` may also enqueue directly. No install prompt is
shown when it is missing. See `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`.

### HTTP API (`ref-api`, optional)

Run a LAN-facing archive server, or point `ref` at an existing one.

**Archive host (this machine owns `~/references`):**

```bash
pipx install ref-cli
ref --install-server              # pipx inject [api], config template, user systemd unit
ref --server-status
ref --uninstall-server

# Manual alternative:
pipx inject ref-cli 'ref-cli[api]'
ref-api                           # foreground, 0.0.0.0:8000
```

`ref --install-server` creates `~/.config/ref/config.yaml` from a documented template when missing, adds `ref-api.env`, enables `ref-api.service` under **user systemd**, and sets `api_url: http://127.0.0.1:8000` when still unset. For boot without login: `loginctl enable-linger $USER`.

**Other machines (clients only):**

```bash
pipx install ref-cli              # no [api] extra required
```

Set `api_url` in `~/.config/ref/config.yaml` to the server URL.

Requires **Python 3.8+** on the host running `ref-api`. **No authentication** yet — bind only on trusted networks.

```bash
pip install 'ref-cli[api]'
# or: pipx inject ref-cli 'ref-cli[api]'
# or: pip install -e '.[api]'

ref-api --host 127.0.0.1 --port 8080
# or: REF_API_HOST / REF_API_PORT
```

```bash
curl -sS http://127.0.0.1:8000/health

# Special characters (?, &, #, spaces, unicode) belong in the JSON body
curl -sS -X POST http://127.0.0.1:8000/urls \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/search?q=hello world&x=1#frag-üñîçødé","force":false}'

curl -sS -X POST http://127.0.0.1:8000/urls \
  -H 'Content-Type: application/json' \
  -d '{"urls":["https://one.example/","https://two.example/"],"force":false}'
```

Response shape: `{"results":[{"input":"…","url":"…","status":"added|exists|skipped|error","message":"…","output":"…"}]}`.

### Using `ref` as an API client

Point the CLI at a running `ref-api` server by setting `api_url` in `~/.config/ref/config.yaml` (or `REF_API_URL` in the environment):

```yaml
api_url: http://192.168.1.10:8000
```

When `api_url` is set:

- `ref <url>` POSTs to `/urls` and prints the same stdout-style lines as local mode
- `ref --search` (and `--search-url`, `--search-title`, etc.) call `GET /search` and render `-Hit Type:` lines as before
- Exit code `1` when ingest returns `error` or the API is unreachable; `0` for added, exists, or skipped
- `ref --backup` downloads a server-side backup into your local `paths.references` directory (respects `--nocompress`)
- `ref --file urls.txt` POSTs each URL to `/urls` (file is read/written locally; archive updates happen on the server)
- `ref --transcript <url>` calls `POST /transcript` on the server

Other commands (`--integrity`, etc.) still run locally on the machine where you invoke `ref`.

### Shell tab completion (bash / zsh)

After installing (pipx or editable), enable completion once in your shell — same pattern as `ol` / `od`:

```bash
# bash — add to ~/.bashrc
eval "$(register-python-argcomplete ref)"
eval "$(register-python-argcomplete ref-advisors)"
eval "$(register-python-argcomplete ref-enrich)"
eval "$(register-python-argcomplete ref-fix-x-titles)"
eval "$(register-python-argcomplete ref-fix-reddit-titles)"

# zsh — add to ~/.zshrc (after compinit)
eval "$(register-python-argcomplete ref)"
eval "$(register-python-argcomplete ref-advisors)"
eval "$(register-python-argcomplete ref-enrich)"
eval "$(register-python-argcomplete ref-fix-x-titles)"
eval "$(register-python-argcomplete ref-fix-reddit-titles)"
```

Then reload the shell (or `source` the rc file). Tab completion covers:

- CLI flags and choice values (`--platform`, `--format`, `--debug`, …)
- Filesystem paths for `--file` / `-o` / `--output`

### Enrichment (YouTube meta cards + categories)

Hybrid storage (A + B):

1. **Thin fields on each row** after `@meta`: `category|role|channel_id`  
2. **Full cards** under `~/references/enrichment/youtube/videos/<id>.json` and `…/channels/<id>.json`

`references.md` starts with a version header. Running `ref` or `ref-enrich` auto-migrates older files (with a gzipped `.bak-*.gz` backup by default).

**On each new YouTube save**, `ref` now also enriches that video (best-effort): writes
`enrichment/youtube/videos/<id>.json` and stamps `|@meta|category|role|channel_id` on the row.
You should see lines like `Enrichment: Education / advisor` and `Meta card: …` after the transcript line.

Batch backfill (history / failures):

```bash
# Single video (URL or 11-char id); refreshes card + matching references.md row
ref-enrich "https://www.youtube.com/watch?v=PqtggjVAi8M"
ref-enrich PqtggjVAi8M --force          # re-fetch even if already enriched

# Default bulk: --limit 50, --rate 30 (live fetches per minute). Cache hits free.
ref-enrich --file ~/references/references.md

# Full archive (~23k): no cap, throttled 30/min — safe to leave running
ref-enrich --limit 0 --rate 30

ref-enrich --limit 0 --rate 60    # faster
ref-enrich --limit 0 --rate 0     # no client throttle
ref-enrich --prefer-ytdlp --limit 10
ref-enrich --dry-run

# Advisors without music libraries (after enrichment)
ref-advisors --exclude-role music --min-count 3
ref-advisors --role advisor --platform youtube
```

Fetch order: YouTube Data API when `YOUTUBE_API_KEY` is set, otherwise **yt-dlp**. Descriptions are scanned for GitHub, Amazon, music, Patreon, Discord links.

**Format upgrades:** `references.md` is versioned. Unversioned files are treated as v1. On `ref` / `ref-enrich`, migrations run **in order** (1→2→…→current) so an old archive layers every hop. The header records `# migration-path: 1→2; …`. New schema versions only add a step in `MIGRATION_STEPS` (`src/ref_cli/references_format.py`).

## Configuration

Configuration lives in `~/.config/ref/config.yaml`. On first run, or when you run `ref --install-server` on a machine without that directory, a **documented template** is copied into place. Optional server env vars: `~/.config/ref/ref-api.env` (see `ref-api.env.template`).

Key settings:

```yaml
api_url: null                    # set to http://host:8000 for client mode
paths:
  references: ~/references
skip_patterns: []                # glob or exact URL skips
```

See the template file after bootstrap for full comments. Override client URL with `REF_API_URL`.

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

### Repair titles in references.md

Two separate utilities re-check stored titles against a fresh fetch and rewrite **only** the title field in place (same line order and other fields). Both default to dry-run; pass `--apply` to write.

```bash
ref-fix-x-titles                 # dry-run for x.com / twitter.com
ref-fix-x-titles --apply         # write updates
ref-fix-x-titles --limit 10      # process at most 10 matching rows

ref-fix-reddit-titles            # dry-run for reddit.com / redd.it
ref-fix-reddit-titles --apply
ref-fix-reddit-titles --file ~/references/references.md --limit 25
```

### Trusted advisors (YouTube + X + web/blogs)

Scan `references.md` and rank people/channels/sites by how often you saved their content. Streaming parse, so large reference files are fine. Use the list to decide who to pull X/YouTube transcripts or blog archives from for voice modeling.

```bash
ref-advisors --file ./references.md              # markdown on stdout (min 2 saves)
ref-advisors --file ./references.md --min-count 5 --top 40
ref-advisors --file ./references.md --platform youtube -o advisors.md
ref-advisors --file ./references.md --platform x --format json -o advisors.json
ref-advisors --file ./references.md --platform web --min-count 2 -o blog-advisors.md
ref-advisors --file ./references.md --format csv -o advisors.csv
```

- **YouTube**: groups by channel/uploader name (pipe characters in names are handled).
- **X**: groups by `@handle` from the URL; display name is taken from titles like `Name on X: "..."`.
- **Web/blogs**: Medium authors (`@handle`, `author.medium.com`, or `| by Author |` titles), Substack authors, and other sites you return to (by domain). Skips aggregators (Reddit, GitHub, Amazon, arXiv, etc.).
- Status messages go to stderr; the report body goes to stdout (or `-o`).

### Other Options

- `ref <url>` - Process a single URL
- `ref --file <file>` - Process URLs from a file
- `ref --search <term>` - Search across all fields
- `ref --transcript <url>` - Update transcript for a YouTube video
- `ref --backup` - Gzip backup of `references.md` (default); `ref --backup --nocompress` for a plain copy
- `ref-fix-x-titles` / `ref-fix-reddit-titles` - Repair stored X or Reddit titles in `references.md` (see above)
- `ref-advisors` - Rank trusted YouTube channels, X handles, and web/blog authors from `references.md`
- `ref-enrich` - YouTube meta cards + `@meta` categories (migrate backups gzip by default; `--nocompress` for plain)

