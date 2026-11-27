"""Pydantic request/response models for the ref API."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# Formal capability contract. Clients (refwatch) can call ``GET /capabilities``
# and check this value instead of guessing support from a package version.
API_CONTRACT_VERSION = "2"

UrlStatus = Literal["added", "exists", "skipped", "error"]
PrimaryStatus = Literal["added", "exists"]
DiscoveryStatus = Literal[
    "queued",
    "already_queued",
    "already_completed",
    "failed",
]


class UrlIngestRequest(BaseModel):
    """Ingest one URL or a list of URLs via JSON (preserves special characters)."""

    url: Optional[str] = Field(default=None, description="Single URL or YouTube video ID")
    urls: Optional[List[str]] = Field(
        default=None,
        description="Multiple URLs / video IDs to process in order",
    )
    force: bool = Field(
        default=False,
        description="Force addition even if the URL already exists",
    )

    @model_validator(mode="after")
    def require_url_or_urls(self) -> "UrlIngestRequest":
        has_url = self.url is not None and str(self.url).strip() != ""
        has_urls = bool(self.urls) and any(u and str(u).strip() for u in self.urls)
        if not has_url and not has_urls:
            raise ValueError("Provide a non-empty 'url' or at least one entry in 'urls'")
        return self

    def iter_inputs(self) -> List[str]:
        """Return ordered non-empty input strings to process."""
        items: List[str] = []
        if self.url is not None and str(self.url).strip():
            items.append(str(self.url).strip())
        if self.urls:
            for u in self.urls:
                if u is not None and str(u).strip():
                    items.append(str(u).strip())
        return items


class PrimaryCapture(BaseModel):
    """Authoritative result of the primary archive operation.

    ``canonical_url`` is the URL actually stored in references.md (after any
    redirect/tracking normalization), never a guessed value and never a child
    URL. ``archive_confirmed`` is true only after an exact archive row check.
    """

    status: PrimaryStatus
    canonical_url: str
    archive_confirmed: bool
    source: str = ""
    identity_recorded: bool = False


class DiscoveryResult(BaseModel):
    """Durable background discovery enqueue result, reported separately."""

    status: DiscoveryStatus
    job_id: Optional[str] = None
    detail: str = ""


class UrlResult(BaseModel):
    """Per-URL outcome from ingest."""

    input: str = Field(description="Original input string from the request")
    url: str = Field(description="URL that was processed (after video-id conversion if any)")
    status: UrlStatus
    message: str = ""
    output: str = Field(
        default="",
        description="Captured stdout from process_url (human-readable diagnostics only)",
    )
    primary: Optional[PrimaryCapture] = Field(
        default=None,
        description="Authoritative primary capture; absent for skipped inputs",
    )
    discovery: Optional[DiscoveryResult] = Field(
        default=None,
        description="Background discovery status, separate from primary capture",
    )
    error: Optional[str] = Field(
        default=None,
        description="Sanitized, actionable failure detail for status=error",
    )


class UrlIngestResponse(BaseModel):
    results: List[UrlResult]


ArchiveLookupStatus = Literal["exists", "canonical", "absent", "unknown", "error"]


class ArchiveLookupResponse(BaseModel):
    """Read-only exact archive lookup result for one input URL.

    ``deletion_safe`` is true only when the response conclusively proves the
    reference is present in the archive (an exact row or a persisted canonical
    identity whose row exactly exists). ``absent``/``unknown``/``error`` are not
    proof that a reference was never captured under another canonical form and
    must be treated fail-closed by deletion workflows.
    """

    input: str
    status: ArchiveLookupStatus
    archive_confirmed: bool = False
    exact_match: bool = False
    deletion_safe: bool = False
    canonical_url: Optional[str] = None
    stored_url: Optional[str] = None
    identity: Literal["exact", "ledger", "none", "unresolved", "invalid"] = "none"
    message: str = ""
    error: Optional[str] = None


class IdempotencyReconciliationResponse(BaseModel):
    """Read-only view of a stored idempotency request key.

    ``results`` stays positionally aligned with ``inputs``: ``None`` marks an
    input that has no durable confirmed result yet (interrupted or still being
    processed).  Do not compact the list; position is the binding contract.
    """

    key: str
    state: Literal["processing", "completed", "ambiguous"]
    request_hash: str
    inputs: List[str]
    force: bool = False
    results: List[Optional[UrlResult]] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: float
    updated_at: float


class CapabilitiesResponse(BaseModel):
    """Explicit backend capability contract for API clients."""

    api_contract_version: str = API_CONTRACT_VERSION
    queue_format_version: int = 1
    features: Dict[str, bool] = Field(default_factory=dict)
    primary_statuses: List[str] = Field(
        default_factory=lambda: ["added", "exists"]
    )
    discovery_statuses: List[str] = Field(
        default_factory=lambda: [
            "queued",
            "already_queued",
            "already_completed",
            "failed",
        ]
    )


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "unknown"
    api_contract_version: str = API_CONTRACT_VERSION


SearchField = Literal["all", "url", "title", "date", "source", "uploader"]


class SearchHit(BaseModel):
    line: str
    hit_types: List[str]


class SearchResponse(BaseModel):
    results: List[SearchHit]


class ListResponse(BaseModel):
    urls: List[str]


TranscriptStatus = Literal["updated", "failure_recorded", "not_found", "error"]


class TranscriptRequest(BaseModel):
    url: str = Field(description="YouTube video URL to update transcript for")


class TranscriptResult(BaseModel):
    url: str
    status: TranscriptStatus
    message: str = ""
    output: str = Field(
        default="",
        description="Captured stdout from update_transcript",
    )


class TranscriptResponse(BaseModel):
    result: TranscriptResult


class QueueStatusResponse(BaseModel):
    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    unfinished: int = 0
    corrupt: int = 0


class RollbackSafetyResponse(BaseModel):
    """Read-only downgrade safety check for outstanding Reddit discovery work."""

    safe: bool
    blocked: bool
    corrupt: bool = False
    blockers: List[Dict[str, Any]] = Field(default_factory=list)
    failed_preserved: int = 0
    reason: str = ""
