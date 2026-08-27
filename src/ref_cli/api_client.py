"""HTTP client for ref-api when ``api_url`` is configured."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import requests

from ref_cli.utils.colors import error, success, url, warning

DEFAULT_INGEST_TIMEOUT = 300
DEFAULT_SEARCH_TIMEOUT = 30
DEFAULT_BACKUP_TIMEOUT = 120


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
        raise ApiError(f"Could not reach ref API at {base_url}: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or response.reason
        raise ApiError(
            f"ref API error ({response.status_code}): {detail}",
            status_code=response.status_code,
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(f"ref API returned invalid JSON from {url_path}") from exc


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
        raise ApiError(f"Could not reach ref API at {base_url}: {exc}") from exc

    if response.status_code >= 400:
        detail = response.text.strip() or response.reason
        raise ApiError(
            f"ref API error ({response.status_code}): {detail}",
            status_code=response.status_code,
        )

    filename = _filename_from_content_disposition(
        response.headers.get("content-disposition")
    )
    if not filename:
        filename = "references.md.gz" if compress else "references.md"

    local_path = os.path.join(dest_dir, os.path.basename(filename))
    with open(local_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                handle.write(chunk)

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
