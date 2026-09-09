"""HTTP routes for the ref API."""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from typing import Optional

from ref_api.schemas import (
    ListResponse,
    SearchField,
    SearchResponse,
    TranscriptRequest,
    TranscriptResponse,
    UrlIngestRequest,
    UrlIngestResponse,
)
from ref_api import service


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
        "synchronous and serialized against references.md."
    ),
)
def ingest_urls(
    body: UrlIngestRequest,
    _auth: None = Depends(require_auth),
) -> UrlIngestResponse:
    inputs = body.iter_inputs()
    if not inputs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a non-empty 'url' or at least one entry in 'urls'",
        )
    results = service.process_many(inputs, force=body.force)
    return UrlIngestResponse(results=results)


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
