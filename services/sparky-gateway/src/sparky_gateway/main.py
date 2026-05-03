"""FastAPI app factory — run with ``uvicorn --factory sparky_gateway.main:create_app``.

See PLAN.md §12 for the gateway requirements and §5.1 for the Phase 3 route set.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from . import (
    agentic_rag_routes,
    audio_routes,
    chat_routes,
    coding_routes,
    errors,
    health,
    jobs_routes,
    media_routes,
    metrics,
    models_routes,
    reasoning_routes,
)
from .config import Settings
from .job_store import JobStore
from .logging_setup import setup_logging
from .registry import load_registry
from .request_id import RequestIdMiddleware
from .request_limits import BodySizeLimitASGI

log = logging.getLogger("sparky_gateway")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    limits = httpx.Limits(
        max_connections=32,
        max_keepalive_connections=max(4, settings.sparky_nemotron_max_inflight * 2),
    )
    timeout = httpx.Timeout(settings.sparky_request_timeout_seconds)
    app.state.http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    app.state.nemotron_sem = asyncio.Semaphore(settings.sparky_nemotron_max_inflight)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


def create_app(settings: Settings | None = None) -> BodySizeLimitASGI:
    """Build the FastAPI app.

    Refuses to boot without `SPARKY_API_KEY` (PLAN §10). The model registry
    is loaded once at startup so `/v1/models` and `/ready` both surface a
    consistent view.
    """
    if settings is None:
        settings = Settings()

    if not settings.sparky_api_key:
        raise RuntimeError(
            "SPARKY_API_KEY is required. Source it from /etc/sparky/sparky.env "
            "(mirrored from MiMi-Secrets sealed secret 'sparky-api-key')."
        )

    setup_logging(settings.sparky_logging_config_path, settings.sparky_log_level)

    doc_urls = settings.sparky_enable_openapi_docs
    app = FastAPI(
        title="Sparky Gateway",
        version="0.1.0",
        description=(
            "Authenticated internal API for Sparky (DGX Spark main intelligence "
            "machine). External callers reach Sparky through this gateway, never "
            "raw runtime ports. See PLAN.md §5 and config/api-contract.yaml."
        ),
        docs_url="/docs" if doc_urls else None,
        redoc_url="/redoc" if doc_urls else None,
        openapi_url="/openapi.json" if doc_urls else None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    app.state.registry = load_registry(settings.sparky_model_registry_path)
    app.state.job_store = JobStore(settings.jobs_dir)

    # Metrics outermost on the FastAPI stack; request id innermost. HTTP body size
    # is capped above this stack via BodySizeLimitASGI (chunk-safe receive).
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(metrics.MetricsMiddleware)

    # FastAPI's add_exception_handler is typed to accept (Request, Exception)
    # but our handlers narrow to specific subclasses. The runtime contract is
    # honored — only matching exceptions reach each handler.
    app.add_exception_handler(HTTPException, errors.http_exception_handler)
    app.add_exception_handler(
        RequestValidationError,
        errors.validation_exception_handler,
    )
    app.add_exception_handler(Exception, errors.unhandled_exception_handler)

    app.include_router(health.router)
    app.include_router(models_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(reasoning_routes.router)
    app.include_router(agentic_rag_routes.router)
    app.include_router(coding_routes.router)
    app.include_router(media_routes.router)
    app.include_router(audio_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(metrics.router)

    log.info(
        "sparky-gateway initialized",
        extra={
            "active_models": len(app.state.registry.active()),
            "bind": settings.sparky_gateway_bind,
        },
    )
    return BodySizeLimitASGI(app, settings.sparky_max_request_body_bytes)


# Run with uvicorn's factory mode so config validation happens at startup,
# not import:
#   uvicorn sparky_gateway.main:create_app --factory --host 0.0.0.0 --port 8080
