"""FastAPI application for ref URL ingest."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ref_api import __version__
from ref_api.routes import router
from ref_api.schemas import HealthResponse

logger = logging.getLogger(__name__)


def _bootstrap_archive() -> None:
    """Ensure reference paths exist and migrate references.md like the CLI main()."""
    from ref_cli import cli as ref_cli

    ref_cli.ensure_path_exists(ref_cli.UNIFIED)
    ref_cli.ensure_path_exists(ref_cli.TRANSCRIPT_PENDING_FILE)
    try:
        from ref_cli.references_format import ensure_references_migrated

        migrate_msg = ensure_references_migrated(
            ref_cli.UNIFIED, backup=True, compress=True
        )
        if migrate_msg:
            logger.info("%s", migrate_msg)
    except Exception as migrate_exc:  # noqa: BLE001 - never block the API
        logger.warning("references.md migrate skipped: %s", migrate_exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _bootstrap_archive()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ref API",
        description=(
            "HTTP API for the same URL archive used by the `ref` CLI: ingest, search, "
            "backup, and transcript update. Auth is not enabled; the router has a "
            "placeholder Depends for a future token."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request, exc: RequestValidationError):
        """Empty or malformed ingest payloads return 400, not 422."""
        return JSONResponse(
            status_code=400,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    app.include_router(router)

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        return HealthResponse(status="ok", version=__version__)

    return app


app = create_app()
