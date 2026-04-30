"""FastAPI app factory — run with ``uvicorn --factory sparky_gateway.main:create_app``.

See PLAN.md §12 for the gateway requirements and §5.1 for the Phase 3 route set.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from . import errors, health, metrics, models_routes
from .config import Settings
from .logging_setup import setup_logging
from .registry import load_registry
from .request_id import RequestIdMiddleware

log = logging.getLogger("sparky_gateway")


def create_app(settings: Settings | None = None) -> FastAPI:
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
    )
    app.state.settings = settings
    app.state.registry = load_registry(settings.sparky_model_registry_path)

    # Order matters: outermost middleware is added LAST. RequestId runs inner
    # so the metrics span fully envelopes id assignment.
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
    app.include_router(metrics.router)

    log.info(
        "sparky-gateway initialized",
        extra={
            "active_models": len(app.state.registry.active()),
            "bind": settings.sparky_gateway_bind,
        },
    )
    return app


# Run with uvicorn's factory mode so config validation happens at startup,
# not import:
#   uvicorn sparky_gateway.main:create_app --factory --host 0.0.0.0 --port 8080
