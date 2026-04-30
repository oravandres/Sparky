"""Error envelope helpers — matches the OpenAPI `Error` schema in api-contract.yaml."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger("sparky_gateway")


def envelope(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if request_id:
        err["request_id"] = request_id
    return {"error": err}


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)  # narrowed by Starlette dispatch
    rid = getattr(request.state, "request_id", None)
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        body: dict[str, Any] = dict(detail)
        if rid:
            body["error"] = {**body["error"], "request_id": rid}
    else:
        body = envelope("http_error", str(detail), rid)
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # narrowed by Starlette dispatch
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content=envelope("invalid_request", "Request validation failed", rid),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected failures — stable JSON envelope + request id for ops."""
    rid = getattr(request.state, "request_id", None)
    log.exception(
        "unhandled_exception",
        extra={"request_id": rid},
    )
    return JSONResponse(
        status_code=500,
        content=envelope(
            "internal_error",
            "An unexpected error occurred",
            rid,
        ),
    )
