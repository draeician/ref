# Debugging the "Error: An unexpected error occurred." image-URL bug

A step-by-step walkthrough of a real production bug, written so the journey
(not just the fix) can be followed and used as a debugging exercise.

---

## 0. TL;DR

`refwatch` (a Discord bot) calls the `ref` CLI to record links. When a Reddit
post linked to a `.jpg` image, `ref` printed `Error: An unexpected error
occurred.` to stdout, which `refwatch` interpreted as a failure and never
acknowledged.

The **root cause** was in `ref_cli/cli.py`: `get_title_from_url()` treated every
URL as an HTML page and ran `lynx -source "<url>"`, then decoded the result as
UTF-8. A JPEG begins with the bytes `0xff 0xd8`, which cannot be decoded as
UTF-8, raising `UnicodeDecodeError`. A broad `except Exception` swallowed it and
returned `"Error: Unexpected error - ..."`.

The **deployment gotcha** (the part that made the fix *appear* not to work) was
that the fix was applied in three separate places that all had to line up:

1. The source tree (`src/ref_cli/cli.py`).
2. The installed `ref`/`ref-api` pipx package (a copy, not the source).
3. A running **`ref-api` systemd service** that `ref` silently routed work to.

Until all three were updated *and* the service restarted, the error kept coming
back — even though the fix was "correct".

---

## 1. The symptom

The `refwatch` service log showed, for a message containing a Reddit link:

```
Found linked URL in Reddit post: https://raw.githubusercontent.com/Daniele-Tomassoni/peerino/main/peerino-website/assets/how-to-send.jpg
Error: An unexpected error occurred.
Found linked URL in Reddit post: https://github.com/Daniele-Tomassoni/peerino
URL https://github.com/Daniele-Tomassoni/peerino already recorded.
Found linked URL in Reddit post: https://peerino.com
URL https://peerino.com already recorded.
```

and

```
refwatch.runner command failed: argv=['/home/draeician/.local/bin/ref', 'https://www.reddit.com/r/coolgithubprojects/s/tbQeDf5UDW'] returncode=0 ...
```

Key observations at a glance:

- Only the **`.jpg`** line is followed by an error; the two normal links are fine.
- The error string is `Error: An unexpected error occurred.` — a *user-visible*
  string, printed to stdout (this matters later: `refwatch` keys off stdout).
- `returncode=0` even though `refwatch` calls it "failed" — so the failure
  signal is **not** the exit code, it's the text on stdout.

---

## 2. Read the code to form a hypothesis

### 2.1 Find the relevant functions

```bash
grep -n "def get_title_from_url\|def _record_general_url" src/ref_cli/cli.py
```

```
830: def get_title_from_url(url: str) -> str:
2280: def _record_general_url(simplified_url: str, force: bool, current_time: str) -> None:
```

### 2.2 Read `get_title_from_url`

The important part (line numbers are approximate; they shift as we edit):

```python
lynx_command = f'lynx -dump -nolist -force_html ... -source "{url}"'
...
result = subprocess.run(lynx_command, shell=True, capture_output=True, text=True, timeout=30)
...
soup = BeautifulSoup(result.stdout, 'html.parser')
...
except Exception as e:
    logging.error(f"An unexpected error occurred: {e}")
    return f"Error: Unexpected error - {e}"
```

### 2.3 Read `_record_general_url`

```python
def _record_general_url(simplified_url, force, current_time):
    title = get_title_from_url(simplified_url)
    ...
    elif title.startswith("Error: Unexpected error"):
        log_error("URL Processing", simplified_url, title)
        print("Error: An unexpected error occurred.")
    ...
```

### 2.4 The hypothesis

`get_title_from_url` runs `lynx -source` on **every** URL. For a `.jpg`, `lynx`
dumps the raw binary image bytes. `subprocess.run(..., text=True)` decodes those
bytes as UTF-8, and the JPEG magic bytes `0xff 0xd8` are invalid UTF-8, so a
`UnicodeDecodeError` is raised inside the `try`, caught by the broad
`except Exception`, and turned into `"Error: Unexpected error - ..."`.

`_record_general_url` sees that string, logs it, and prints
`Error: An unexpected error occurred.` — which `refwatch` then treats as a
failure.

> **Debugging principle:** read the code *before* changing anything. The bug was
> fully explainable from the source: a broad `except` masking a decode error, and
> a caller that turns a sentinel string into user-visible text.

---

## 3. The fix

Three small changes in `src/ref_cli/cli.py`:

1. Import `unquote`:

   ```python
   from urllib.parse import urlparse, urlunparse, parse_qs, quote, unquote
   ```

2. Add an early guard that skips known image extensions **before** calling `lynx`:

   ```python
   _IMAGE_EXTENSIONS = {
       ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
       ".ico", ".tif", ".tiff", ".avif", ".heic", ".heif",
   }

   def get_title_from_url(url: str) -> str:
       ...
       parsed = urlparse(url)
       if Path(unquote(parsed.path)).suffix.lower() in _IMAGE_EXTENSIONS:
           verbose_logger.log(f"Skipping title fetch for image URL: {url}")
           return "Image URL (no title)"
       ...
   ```

   `"Image URL (no title)"` does **not** start with `"Error"`, so
   `_record_general_url` falls into its `elif title and not title.startswith("Error")`
   branch and records the link normally — no error is logged, no error is printed.

3. Harden the subprocess call so a binary body can never raise
   `UnicodeDecodeError` even for non-image binary URLs:

   ```python
   result = subprocess.run(lynx_command, shell=True, capture_output=True, text=True, errors="ignore", timeout=30)
   ```

`errors="ignore"` tells Python to drop undecodable bytes instead of raising.

> **Debugging principle:** fix at the boundary where the bad assumption lives
> ("every URL is HTML"), and also add a cheap belt-and-suspenders guard at the
> next layer down (decode errors) so a different binary type can't reproduce the
> same crash.

---

## 4. "It's still broken" — the installed artifact was stale

After committing the fix, the user reported the **exact same error**. The first
trap: editing the source tree does not update the installed program.

### 4.1 Inspect what actually runs

```bash
head -1 /home/draeician/.local/bin/ref
# #!/home/draeician/.local/share/pipx/venvs/ref-cli/bin/python

ls -la /home/draeician/.local/bin/ref
# ... ref -> /home/draeician/.local/share/pipx/venvs/ref-cli/bin/ref
```

`ref` is installed via **pipx**, and pipx installs a *copy* of the code into its
own virtualenv — it is **not** the source tree.

### 4.2 Compare the installed version to the source

```bash
pipx list
#   package ref-cli 1.6.12b1.dev15+g5642e2e44, installed using Python 3.12.3
```

The `+g5642e2e44` is a `setuptools_scm` Git hash. The source was already at
commit `fb3042b` (our fix), but the installed package was pinned at `5642e2e` —
**older than the fix**.

Confirm by grepping the *installed* file:

```bash
VENV=/home/draeician/.local/share/pipx/venvs/ref-cli
grep -l "_IMAGE_EXTENSIONS" $VENV/lib/python*/site-packages/ref_cli/cli.py \
  && echo "FIX INSTALLED" || echo "STALE"
# STALE
```

> **Debugging principle:** when "the code is right but the behavior is wrong",
> ask *which copy of the code is actually executing*. For Python CLI tools,
> check `which`, the shebang, `pipx list` / `pip show`, and grep the installed
> `site-packages` file — not just the repo.

### 4.3 Reinstall from source

```bash
pipx install --force .
# installed package ref-cli 1.6.12b1.dev17+gfb3042b33
```

Verify:

```bash
grep -c "_IMAGE_EXTENSIONS" $VENV/lib/python*/site-packages/ref_cli/cli.py
# 2
```

---

## 5. Still broken after reinstall — the routing twist

After reinstalling, the error **still** appeared. This is where a naive debugger
stops and re-reads the same code; the actual issue was elsewhere.

### 5.1 Reproduce in isolation

Call the function directly through the same interpreter:

```python
$VENV/bin/python -c "
from ref_cli.cli import get_title_from_url, simplify_url, resolve_redirect
u='https://raw.githubusercontent.com/Daniele-Tomassoni/peerino/main/peerino-website/assets/how-to-send.jpg'
r = resolve_redirect(u)
s = simplify_url(r)
print('simplify_url ->', s)
print('title ->', get_title_from_url(s))
"
# title -> Image URL (no title
```

And even call the full `process_url` directly:

```python
$VENV/bin/python -c "
import ref_cli.cli as m
m.process_url('https://raw.githubusercontent.com/.../how-to-send.jpg', False)
"
# 2026-09-29T13:14:43|[https://.../how-to-send.jpg]|(Image URL (no title))|General|General
```

The library-level code works. But the `ref` binary still fails:

```bash
/home/draeician/.local/bin/ref 'https://raw.githubusercontent.com/.../how-to-send.jpg'
# Error: An unexpected error occurred.
```

> **Debugging principle:** when a function works in isolation but not through
> the actual entry point, the difference is the *path taken to reach it*. Stop
> testing the leaf function and start tracing the entry point.

### 5.2 Find the difference between `ref` and `process_url`

The entry point is `main()` → `run_ingest()` → `process_url()`. But `run_ingest`
has a branch we skipped when we called `process_url` directly:

```python
def run_ingest(raw_input, force=False):
    api_base = configured_api_base_url()
    if api_base:
        from ref_cli.api_client import ingest_via_api
        ...
        sys.exit(ingest_via_api(api_base, raw_input, force=force))
    ...
```

If an `api_url` is configured, `ref` does **not** process the URL locally — it
sends it to a running `ref-api` HTTP server. Check:

```python
$VENV/bin/python -c "import ref_cli.cli as m; print(m.configured_api_base_url())"
# http://127.0.0.1:8000
```

That explains everything: we fixed the local `ref` and `ref_cli` library, but the
*actual work* (and the error string) came from a separate **`ref-api` server**
process that was still running old code.

> **Debugging principle:** "the fix doesn't work" often means "you fixed the
> wrong process." Find out who is *actually* doing the work before iterating on
> the fix again.

---

## 6. Finding the real culprit: the `ref-api` service

### 6.1 Inspect the server

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","version":"1.6.12b1.dev15+g5642e2e44"}
```

Same stale hash (`5642e2e`) as the old pipx install. Find the process:

```bash
ss -tlnp | grep 8000
# LISTEN 0 2048 0.0.0.0:8000 ... users:(("ref-api",pid=1464,fd=14))

tr '\0' ' ' < /proc/1464/cmdline
# /home/draeician/.local/share/pipx/venvs/ref-cli/bin/python /home/draeician/.local/bin/ref-api --host 0.0.0.0 --port 8000
```

It's the **same pipx venv** we just reinstalled — but the process had been
running since before the reinstall and still had the old code loaded in memory.

### 6.2 Identify the service

```bash
find ~/.config/systemd -name '*ref*'
# .../user/ref-api.service
# .../user/refwatch.service
```

It's a **user-level systemd unit** (`systemctl --user`), not a system service.

### 6.3 Restart it to pick up the new code

```bash
systemctl --user restart ref-api.service
curl -s http://127.0.0.1:8000/health
# {"status":"ok","version":"1.6.12b1.dev17+gfb3042b33"}
```

Now the server reports the fixed version.

> **Debugging principle:** a long-running daemon keeps the *code it loaded at
> startup* in memory. Reinstalling the package on disk does nothing until the
> daemon restarts. Always restart the service after deploying a code change.

---

## 7. Verify the fix end-to-end

```bash
/home/draeician/.local/bin/ref 'https://www.reddit.com/r/coolgithubprojects/s/tbQeDf5UDW'
```

```
URL https://www.reddit.com/.../i_built_peerino_... already recorded.
Found linked URL in Reddit post: https://raw.githubusercontent.com/.../how-to-send.jpg
URL https://raw.githubusercontent.com/.../how-to-send.jpg already recorded.
Found linked URL in Reddit post: https://github.com/Daniele-Tomassoni/peerino
URL https://github.com/Daniele-Tomassoni/peerino already recorded.
Found linked URL in Reddit post: https://peerino.com
URL https://peerino.com already recorded.
```

No `Error: An unexpected error occurred.` — the `.jpg` is now handled as an
image URL (and shows as "already recorded" because our earlier direct
`process_url` test had already inserted it).

---

## 8. Follow-up improvement

The same "multiple commands" trap from §4 and §6 (reinstall package, then
restart service) also applied to *upgrading* `ref`. The `ref --upgrade` command
only printed instructions. We changed it to actually execute the steps:

- `src/ref_cli/upgrade.py`: added `perform_upgrade()` which runs each step
  (`pipx install --force <source>` / `pipx upgrade ref-cli`, then
  `pipx inject ref-cli 'ref-cli[api]'` when the api extra is present, then
  `systemctl --user restart ref-api` when the unit exists).
- `src/ref_cli/cli.py`: `--upgrade` now calls `perform_upgrade()`.
- `tests/test_upgrade.py`: added coverage (13 tests pass).

So `ref --upgrade` now does the package reinstall *and* the service restart in a
single command.

---

## 9. Command reference

| Purpose | Command |
| --- | --- |
| Locate a function | `grep -n "def get_title_from_url" src/ref_cli/cli.py` |
| What binary runs | `head -1 /home/draeician/.local/bin/ref` |
| Which pipx version | `pipx list` |
| Is the fix in the installed copy? | `grep -l "_IMAGE_EXTENSIONS" $VENV/lib/python*/site-packages/ref_cli/cli.py` |
| Reinstall from source | `pipx install --force .` |
| Reproduce in isolation | `$VENV/bin/python -c "import ref_cli.cli as m; print(m.get_title_from_url('...'))"` |
| Is work routed to an API? | `$VENV/bin/python -c "import ref_cli.cli as m; print(m.configured_api_base_url())"` |
| Server version | `curl -s http://127.0.0.1:8000/health` |
| Who listens on 8000 | `ss -tlnp \| grep 8000` |
| Process command line | `tr '\0' ' ' < /proc/<pid>/cmdline` |
| Find the unit file | `find ~/.config/systemd -name '*ref*'` |
| Restart the service | `systemctl --user restart ref-api.service` |
| Run the tests | `python3 -m pytest tests/test_upgrade.py -q` |

---

## 10. Debugging methodology takeaways

1. **Read the code first.** The entire root cause was visible in the source
   (broad `except` + `text=True` decode). No reproduction was needed to
   understand *why*.

2. **Fix at the assumption, not the symptom.** The bug was "treats every URL as
   HTML". The guard targets that assumption; `errors="ignore"` is a secondary
   safety net.

3. **Ask "which copy is running?"** Source trees, pipx venvs, and long-running
   daemons can all diverge. A correct fix that "doesn't work" is usually a
   deployment/versioning issue, not a logic issue.

4. **Reproduce in isolation to narrow the search.** Calling the leaf function
   directly proved the fix was correct, which redirected attention to the entry
   point and the routing layer.

5. **Trace the actual control flow.** The function worked in isolation but not
   via `ref`; the difference was a single `if api_base:` branch that routed work
   to a different process entirely.

6. **Restart daemons after deploy.** Reinstalling a package updates the files on
   disk, not the code already loaded into a running service's memory.

7. **Keep sentinel strings meaningful.** A generic `"Error: Unexpected error"`
   printed to stdout became a *protocol* between `ref` and `refwatch`. Knowing
   that downstream tooling keys off stdout was essential to understanding the
   blast radius of the bug.
