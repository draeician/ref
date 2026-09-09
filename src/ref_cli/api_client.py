"""HTTP client for ref-api when ``api_url`` is configured."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from ref_cli.utils.colors import error, info, success, url, warning

DEFAULT_INGEST_TIMEOUT = 300
DEFAULT_SEARCH_TIMEOUT = 30
DEFAULT_BACKUP_TIMEOUT = 120
DEFAULT_HEALTH_TIMEOUT = 5


class ApiError(Exception):
    """ref-api request failed."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def get_api_base_url(config: dict) -> Optional[str]:
    """Return configured API base URL, or None for local-only mode."""
    raw = os.environ.get("REF_API_URL") or config.get("api_url")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "false", "0"}:
        return None
    return text.rstrip("/")


def api_base_is_local(base_url: str) -> bool:
    """True when ``api_url`` targets this machine (loopback or local hostname).

    Used so archive-host commands like ``ref --backup`` can use the local file
    instead of HTTP-round-tripping to the co-located ref-api.
    """
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return False
    if host in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        import socket

        local_names = {socket.gethostname().lower(), socket.getfqdn().lower()}
    except OSError:
        return False
    return host in local_names


def _endpoint_label(base_url: str) -> str:
    """Human-readable host:port from api_url for error messages."""
    parsed = urlparse(base_url)
    host = parsed.hostname or base_url
    if parsed.port is not None:
        return f"{host}:{parsed.port}"
    if parsed.scheme == "https":
        return f"{host}:443"
    if parsed.scheme == "http":
        return f"{host}:80"
    return host


def _looks_like_html(text: str, content_type: str = "") -> bool:
    ctype = (content_type or "").lower()
    if "text/html" in ctype:
        return True
    sample = (text or "")[:200].lstrip().lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html")


def _short_body_snippet(text: str, limit: int = 120) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1] + "…"


def _format_connection_error(base_url: str, exc: Exception) -> str:
    """Explain why the client could not reach ref-api (host/port oriented)."""
    label = _endpoint_label(base_url)
    hint = (
        f"Check api_url in ~/.config/ref/config.yaml (or REF_API_URL). "
        f"Expected a running ref-api, e.g. http://minion:8000 — currently {base_url}"
    )

    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return (
            f"Could not connect to ref API at {label}: connection timed out. {hint}"
        )
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return (
            f"ref API at {label} did not respond in time (read timeout). "
            f"The server may be busy; try again or raise the timeout."
        )
    if isinstance(exc, requests.exceptions.ConnectionError):
        cause = str(exc).lower()
        if "name or service not known" in cause or "nodename nor servname" in cause:
            return (
                f"Could not resolve host for ref API ({label}). "
                f"Check the hostname in api_url ({base_url})."
            )
        if "connection refused" in cause or "actively refused" in cause:
            return (
                f"Connection refused to ref API at {label} "
                f"(nothing accepting connections on that host/port). {hint}"
            )
        if "network is unreachable" in cause:
            return (
                f"Network unreachable to ref API at {label}. "
                f"Check LAN/VPN routing to that host."
            )
        return f"Could not connect to ref API at {label}: {exc}. {hint}"

    return f"Could not reach ref API at {label} ({base_url}): {exc}. {hint}"


def _format_http_error(base_url: str, response: requests.Response) -> str:
    """Explain HTTP failures without dumping HTML error pages."""
    label = _endpoint_label(base_url)
    code = response.status_code
    body = response.text or ""
    content_type = response.headers.get("content-type", "")
    hint = (
        f"Check api_url in ~/.config/ref/config.yaml (or REF_API_URL); "
        f"it should point at the ref-api host (currently {base_url})."
    )

    if _looks_like_html(body, content_type):
        # Wrong host / reverse proxy / non-ref service answering this port.
        if code == 403:
            return (
                f"ref API at {label} returned HTTP 403 Forbidden with an HTML page "
                f"(not a ref-api JSON response). Something else is answering on that "
                f"host/port, or a proxy is blocking the request. {hint}"
            )
        if code == 404:
            return (
                f"ref API at {label} returned HTTP 404 with an HTML page "
                f"(not ref-api). Wrong host/port or path? {hint}"
            )
        return (
            f"ref API at {label} returned HTTP {code} with an HTML page "
            f"(not a ref-api JSON response). Wrong host/port? {hint}"
        )

    # Prefer FastAPI-style JSON detail when present.
    try:
        payload = response.json()
        detail = payload.get("detail", payload)
        if isinstance(detail, list):
            detail = "; ".join(str(item) for item in detail)
        detail_text = str(detail)
    except ValueError:
        detail_text = _short_body_snippet(body) or response.reason or "no body"

    if code == 403:
        return (
            f"ref API at {label} returned HTTP 403 Forbidden: {detail_text}. {hint}"
        )
    if code == 404:
        return (
            f"ref API at {label} returned HTTP 404 Not Found: {detail_text}. "
            f"Is ref-api running and up to date on that host?"
        )

    return f"ref API at {label} returned HTTP {code}: {detail_text}"


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    timeout: float,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> dict:
    url_path = f"{base_url}{path}"
    try:
        response = requests.request(
            method,
            url_path,
            params=params,
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ApiError(_format_connection_error(base_url, exc)) from exc

    if response.status_code >= 400:
        raise ApiError(
            _format_http_error(base_url, response),
            status_code=response.status_code,
        )

    try:
        return response.json()
    except ValueError as exc:
        label = _endpoint_label(base_url)
        raise ApiError(
            f"ref API at {label} returned non-JSON from {url_path} "
            f"(is api_url pointing at ref-api? currently {base_url})"
        ) from exc


def check_health(
    base_url: str,
    *,
    timeout: float = DEFAULT_HEALTH_TIMEOUT,
) -> Dict[str, Any]:
    """GET /health and return the JSON body."""
    return _request_json(
        "GET",
        base_url,
        "/health",
        timeout=timeout,
    )


def report_api_status(config: Optional[dict] = None) -> int:
    """
    Print client mode and ref-api connectivity.

    Exit 0 when healthy (or local-only with no api_url).
    Exit 1 when api_url is set but the health check fails.
    """
    cfg = config if config is not None else {}
    base_url = get_api_base_url(cfg)
    if not base_url:
        print(info("Mode: local (api_url not set)"))
        print(
            info(
                "ref uses local files only. Set api_url in ~/.config/ref/config.yaml "
                "(or REF_API_URL) to use a remote ref-api."
            )
        )
        return 0

    label = _endpoint_label(base_url)
    print(info(f"Mode: remote"))
    print(info(f"api_url: {base_url} ({label})"))
    try:
        health = check_health(base_url)
    except ApiError as exc:
        print(error(f"Status: unreachable"))
        print(error(str(exc)))
        return 1

    status = health.get("status", "unknown")
    version = health.get("version", "unknown")
    if status == "ok":
        print(success(f"Status: ok (version {version})"))
        return 0

    print(warning(f"Status: {status} (version {version})"))
    return 1


def ingest_urls(
    base_url: str,
    *,
    url_value: Optional[str] = None,
    urls: Optional[List[str]] = None,
    force: bool = False,
    timeout: float = DEFAULT_INGEST_TIMEOUT,
) -> List[Dict[str, Any]]:
    payload: Dict[str, Any] = {"force": force}
    if url_value is not None:
        payload["url"] = url_value
    if urls is not None:
        payload["urls"] = urls
    data = _request_json(
        "POST",
        base_url,
        "/urls",
        timeout=timeout,
        json_body=payload,
    )
    return data.get("results", [])


def search_refs(
    base_url: str,
    term: str,
    *,
    field: str = "all",
    timeout: float = DEFAULT_SEARCH_TIMEOUT,
) -> List[Dict[str, Any]]:
    data = _request_json(
        "GET",
        base_url,
        "/search",
        timeout=timeout,
        params={"q": term, "field": field},
    )
    return data.get("results", [])


def list_refs(
    base_url: str,
    *,
    limit: Optional[int] = None,
    since: Optional[str] = None,
    timeout: float = DEFAULT_SEARCH_TIMEOUT,
) -> List[str]:
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if since is not None:
        params["since"] = since
    data = _request_json(
        "GET",
        base_url,
        "/list",
        timeout=timeout,
        params=params,
    )
    urls = data.get("urls", [])
    return [str(u) for u in urls]


def print_ingest_results(results: List[Dict[str, Any]]) -> int:
    """Render ingest results like local ``ref``; return shell exit code."""
    exit_code = 0
    for item in results:
        status = item.get("status", "error")
        output = (item.get("output") or "").strip()
        target = item.get("url") or item.get("input") or ""

        if status == "skipped":
            print(warning(f"Skipping URL (matches skip pattern): {url(target)}"))
            continue

        if output:
            print(output)
            if status == "error":
                exit_code = 1
            continue

        if status == "error":
            message = item.get("message") or "Processing failed"
            print(error(message))
            exit_code = 1

    return exit_code


def print_search_results(results: List[Dict[str, Any]]) -> None:
    """Render search results like local ``ref --search``."""
    for item in results:
        line = (item.get("line") or "").strip()
        if line:
            print(line)
        for hit_type in item.get("hit_types") or []:
            print(f"-Hit Type: {hit_type}")


def ingest_via_api(
    base_url: str,
    raw_input: str,
    *,
    force: bool = False,
) -> int:
    try:
        results = ingest_urls(base_url, url_value=raw_input, force=force)
    except ApiError as exc:
        print(error(str(exc)))
        return 1
    return print_ingest_results(results)


def search_via_api(
    base_url: str,
    term: str,
    *,
    field: str = "all",
) -> int:
    try:
        results = search_refs(base_url, term, field=field)
    except ApiError as exc:
        print(error(str(exc)))
        return 1
    print_search_results(results)
    return 0


def list_via_api(
    base_url: str,
    *,
    limit: Optional[int] = None,
    since: Optional[str] = None,
) -> int:
    try:
        urls = list_refs(base_url, limit=limit, since=since)
    except ApiError as exc:
        print(error(str(exc)))
        return 1
    for entry_url in urls:
        print(entry_url)
    return 0


def _filename_from_content_disposition(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    if match:
        return match.group(1).strip()
    return None


def download_backup(
    base_url: str,
    dest_dir: str,
    *,
    compress: bool = True,
    timeout: float = DEFAULT_BACKUP_TIMEOUT,
) -> str:
    """Request a server backup and save it under ``dest_dir``."""
    os.makedirs(dest_dir, exist_ok=True)
    url_path = f"{base_url}/backup"
    try:
        response = requests.post(
            url_path,
            params={"compress": str(compress).lower()},
            stream=True,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ApiError(_format_connection_error(base_url, exc)) from exc

    if response.status_code >= 400:
        # Drain a small prefix so error formatting can inspect HTML bodies
        # when the response was requested with stream=True.
        try:
            peek = next(response.iter_content(chunk_size=4096), b"")
            if peek and not getattr(response, "_content", None):
                response._content = peek
        except Exception:  # noqa: BLE001
            pass
        raise ApiError(
            _format_http_error(base_url, response),
            status_code=response.status_code,
        )

    filename = _filename_from_content_disposition(
        response.headers.get("content-disposition")
    )
    if not filename:
        filename = "references.md.gz" if compress else "references.md"

    local_path = os.path.join(dest_dir, os.path.basename(filename))
    # Write to a sibling temp path first. On the archive host, dest_dir is the
    # same directory the API just wrote the backup into; opening local_path for
    # write would truncate the file mid-stream (IncompleteRead /
    # Content-Length mismatch).
    tmp_path = f"{local_path}.partial"
    try:
        with open(tmp_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    handle.write(chunk)
        os.replace(tmp_path, local_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    return local_path


def backup_via_api(
    base_url: str,
    dest_dir: str,
    *,
    compress: bool = True,
) -> int:
    try:
        local_path = download_backup(base_url, dest_dir, compress=compress)
    except ApiError as exc:
        print(error(str(exc)))
        return 1
    kind = "gzip" if compress else "plain"
    print(success(f"Backup downloaded ({kind}): {local_path}"))
    return 0


def print_transcript_result(result: Dict[str, Any]) -> int:
    """Render transcript update output like local ``ref --transcript``."""
    output = (result.get("output") or "").strip()
    if output:
        print(output)
    status = result.get("status", "error")
    if status == "error":
        if not output:
            print(error(result.get("message") or "Transcript update failed"))
        return 1
    return 0


def update_transcript_via_api(base_url: str, video_url: str) -> int:
    try:
        data = _request_json(
            "POST",
            base_url,
            "/transcript",
            timeout=DEFAULT_INGEST_TIMEOUT,
            json_body={"url": video_url},
        )
    except ApiError as exc:
        print(error(str(exc)))
        return 1
    return print_transcript_result(data.get("result", {}))


def ingest_file_via_api(
    base_url: str,
    file_path: str,
    *,
    force: bool = False,
) -> None:
    """
    Read URLs from a local file and POST each one to ref-api.

    Mirrors ``read_urls_from_file``: comments out processed/skipped lines locally;
    leaves errored lines unchanged on API connection failures.
    """
    import time

    from ref_cli import cli as ref_cli

    user_config = ref_cli.load_config()

    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found")
        return

    modified_lines: List[str] = []
    for line_number, line in enumerate(lines, 1):
        original_line = line
        url_string = line.strip()

        if not url_string or url_string.startswith("#"):
            modified_lines.append(original_line)
            continue

        if ref_cli.should_skip_url(url_string, user_config):
            print(warning(f"Skipping URL (matches skip pattern): {url(url_string)}"))
            modified_lines.append(f"# {original_line}")
            continue

        try:
            results = ingest_urls(base_url, url_value=url_string, force=force)
            print_ingest_results(results)
            modified_lines.append(f"# {original_line}")
        except ApiError as exc:
            print(error(str(exc)))
            modified_lines.append(original_line)
            print(f"Error processing URL on line {line_number}: {exc}")

        time.sleep(1)

    with open(file_path, "w", encoding="utf-8") as handle:
        handle.writelines(modified_lines)
