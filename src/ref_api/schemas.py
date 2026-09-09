"""Pydantic request/response models for the ref API."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


UrlStatus = Literal["added", "exists", "skipped", "error"]


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


class UrlResult(BaseModel):
    """Per-URL outcome from ingest."""

    input: str = Field(description="Original input string from the request")
    url: str = Field(description="URL that was processed (after video-id conversion if any)")
    status: UrlStatus
    message: str = ""
    output: str = Field(
        default="",
        description="Captured stdout from process_url (reference line or status text)",
    )


class UrlIngestResponse(BaseModel):
    results: List[UrlResult]


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "unknown"


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
