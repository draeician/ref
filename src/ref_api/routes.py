"""HTTP routes for the ref API."""

import os

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import FileResponse

from typing import List, Optional

from ref_api.schemas import (
    API_CONTRACT_VERSION,
    ArchiveLookupResponse,
    CapabilitiesResponse,
    IdempotencyReconciliationResponse,
    ListResponse,
    QueueStatusResponse,
    RollbackSafetyResponse,
    SearchField,
    SearchResponse,
    TranscriptRequest,
    TranscriptResponse,
    UrlIngestRequest,
    UrlIngestResponse,
    UrlResult,
)
from ref_api import service
from ref_api.state_store import (
    IdempotencyAmbiguous,
    IdempotencyConflict,
    StateStoreError,
)


async def require_auth() -> None:
    """
    Auth placeholder for a future bearer/API token.

    Phase 1: no authentication. Keep this Depends() on protected routes so a
    token check can be added later without reshaping the router.
    """
    return None


router = APIRouter()


@router.post(
    "/urls",
    response_model=UrlIngestResponse,
    summary="Record one or more URLs",
    description=(
        "Accepts JSON with `url` and/or `urls`. Pass the full URL in the body "
        "so query chars (?, &, #) and unicode are preserved. Ingest is "
        "synchronous for the primary archive write; supported discovery "
        "(YouTube/Reddit) is durably queued for the background worker. "
        "Send an optional `Idempotency-Key` header to make retries safe."
    ),
)
def ingest_urls(
    body: UrlIngestRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(
        default=None,
        alias="Idempotency-Key",
        description=(
            "Optional client-generated key. Same key + same payload is replayed "
            "from durable server state; a different payload returns 409."
        ),
    ),
    _auth: None = Depends(require_auth),
) -> UrlIngestResponse:
    inputs = body.iter_inputs()
    if not inputs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a non-empty 'url' or at least one entry in 'urls'",
        )
    key = (idempotency_key or "").strip()
    if idempotency_key is not None and not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be non-empty when supplied",
        )
    if len(key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be at most 200 characters",
        )
    if not key:
        results = service.process_many(inputs, force=body.force)
        return UrlIngestResponse(results=results)

    try:
        results, replayed = service.process_many_idempotent(
            inputs,
            idempotency_key=key,
            force=body.force,
        )
    except IdempotencyAmbiguous as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except StateStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Idempotency state is unavailable: {exc}",
        ) from exc
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return UrlIngestResponse(results=results)


@router.get(
    "/urls/exists",
    response_model=ArchiveLookupResponse,
    summary="Exact read-only archive lookup",
    description=(
        "Return whether a URL is already recorded. `exists` means an exact "
        "parsed archive row matches the input. `canonical` means a persisted "
        "identity from an earlier confirmed capture maps the input to a stored "
        "URL that exactly exists. `absent`, `unknown` and `error` are distinct. "
        "This endpoint never ingests, enqueues, rewrites or normalizes/guesses."
    ),
)
def url_exists(
    url: str,
    _auth: None = Depends(require_auth),
) -> ArchiveLookupResponse:
    if not (url or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'url' must be non-empty",
        )
    return service.lookup_url(url)


@router.get(
    "/requests/{idempotency_key}",
    response_model=IdempotencyReconciliationResponse,
    summary="Read-only idempotency request reconciliation",
    description=(
        "Return durable state for an `Idempotency-Key` without re-running work. "
        "Use this to reconcile an ambiguous POST timeout."
    ),
)
def idempotency_request_status(
    idempotency_key: str,
    _auth: None = Depends(require_auth),
) -> IdempotencyReconciliationResponse:
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency key must be non-empty",
        )
    try:
        entry = service.get_idempotency_request(key)
    except StateStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Idempotency state is unavailable: {exc}",
        ) from exc
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unknown idempotency key",
        )
    raw_results = list(entry.get("results", []))
    inputs = list(entry.get("inputs", []))
    results: List[Optional[UrlResult]] = [None] * len(inputs)
    for index, raw in enumerate(raw_results[: len(inputs)]):
        if raw is None:
            continue
        try:
            results[index] = UrlResult(**raw)
        except Exception:  # noqa: BLE001 - never hide accepted state behind one bad row
            results[index] = None
    return IdempotencyReconciliationResponse(
        key=key,
        state=entry["state"],
        request_hash=entry["request_hash"],
        inputs=inputs,
        force=bool(entry.get("force", False)),
        results=results,
        error=entry.get("error") or None,
        created_at=float(entry["created_at"]),
        updated_at=float(entry["updated_at"]),
    )


@router.get(
    "/capabilities",
    response_model=CapabilitiesResponse,
    summary="Explicit API capability contract",
    description=(
        "Advertise the structured ingest contract so clients can detect support "
        "without guessing from package version strings."
    ),
)
def capabilities(
    _auth: None = Depends(require_auth),
) -> CapabilitiesResponse:
    return CapabilitiesResponse(
        api_contract_version=API_CONTRACT_VERSION,
        queue_format_version=1,
        features={
            "structured_primary": True,
            "exact_url_lookup": True,
            "deletion_safe_lookup": True,
            "idempotency_key": True,
            "idempotency_ambiguous_state": True,
            "async_youtube_discovery": True,
            "async_reddit_discovery": True,
            "discovery_status": True,
            "rollback_safety_check": True,
        },
    )


@router.get(
    "/urls",
    response_model=ListResponse,
    summary="Dump stored URLs for a domain",
    description=(
        "Return every URL whose parsed hostname is ``domain`` or a subdomain of "
        "it (case-insensitive), newest first. Read-only: the archive is only "
        "parsed, never written. Pass a bare domain such as ``example.com``, not a "
        "URL; paths, query strings, and fragments are returned exactly as stored."
    ),
)
def dump_urls_by_domain(
    domain: str,
    _auth: None = Depends(require_auth),
) -> ListResponse:
    value = (domain or "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'domain' must be non-empty",
        )
    try:
        urls = service.list_urls_for_domain(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ListResponse(urls=urls)


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search references",
    description=(
        "Search references.md by term. ``field=all`` searches every column "
        "(same as ``ref --search``). Other values match ``--search-url``, "
        "``--search-title``, etc."
    ),
)
def search_refs(
    q: str,
    field: SearchField = "all",
    _auth: None = Depends(require_auth),
) -> SearchResponse:
    if not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query parameter 'q' must be non-empty",
        )
    try:
        results = service.search_archive(q, field)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return SearchResponse(results=results)


@router.get(
    "/list",
    response_model=ListResponse,
    summary="List recent reference URLs",
    description=(
        "Return URLs from references.md. Provide exactly one of ``limit`` "
        '(last N added) or ``since`` (duration window, e.g. "1 hour", "5 min"). '
        "Matches ``ref --list``."
    ),
)
def list_refs(
    limit: Optional[int] = None,
    since: Optional[str] = None,
    _auth: None = Depends(require_auth),
) -> ListResponse:
    since_value = (since or "").strip() or None
    if (limit is None) == (since_value is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of query parameters 'limit' or 'since'",
        )
    try:
        urls = service.list_archive(limit=limit, since=since_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ListResponse(urls=urls)


@router.post(
    "/backup",
    summary="Back up references.md",
    description=(
        "Create a timestamped backup of references.md on the server and return "
        "the file for download. Matches ``ref --backup`` (gzip by default)."
    ),
)
def backup_references(
    compress: bool = True,
    _auth: None = Depends(require_auth),
) -> FileResponse:
    try:
        backup_path = service.create_references_backup(compress=compress)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="references.md not found on server",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    media_type = "application/gzip" if compress else "text/markdown"
    return FileResponse(
        backup_path,
        filename=os.path.basename(backup_path),
        media_type=media_type,
    )


@router.post(
    "/transcript",
    response_model=TranscriptResponse,
    summary="Update transcript for a YouTube entry",
    description=(
        "Fetch and store a transcript for an existing YouTube row in references.md "
        "that still has ``|None`` as its transcript field. Same as ``ref --transcript``."
    ),
)
def update_transcript(
    body: TranscriptRequest,
    _auth: None = Depends(require_auth),
) -> TranscriptResponse:
    if not body.url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a non-empty 'url'",
        )
    result = service.update_transcript_for_url(body.url)
    return TranscriptResponse(result=result)


@router.get(
    "/queue",
    response_model=QueueStatusResponse,
    summary="Show-note background queue status",
    description=(
        "Counts of automatically discovered show-note child URLs awaiting/being "
        "processed by the background worker. Useful after a client read timeout: a "
        "non-zero ``unfinished`` count means child work is still outstanding."
    ),
)
def queue_status(
    _auth: None = Depends(require_auth),
) -> QueueStatusResponse:
    return QueueStatusResponse(**service.queue_status())


@router.get(
    "/queue/rollback-safety",
    response_model=RollbackSafetyResponse,
    summary="Read-only downgrade safety check",
    description=(
        "Report whether an older ref-api could be started without consuming "
        "incompatible outstanding jobs. Pending/running Reddit discovery jobs "
        "block downgrade because an older build would mark them done as no-op "
        "YouTube jobs. This endpoint never mutates the queue."
    ),
)
def queue_rollback_safety(
    _auth: None = Depends(require_auth),
) -> RollbackSafetyResponse:
    return RollbackSafetyResponse(**service.rollback_safety())
