"""ASGI middleware — request size guard for chat and large JSON routes (PLAN §12)."""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from .config import Settings


def _payload_too_large_response(max_bytes: int) -> Response:
    body = json.dumps(
        {
            "error": {
                "code": "payload_too_large",
                "message": f"request body exceeds {max_bytes} bytes",
            }
        }
    ).encode()
    return Response(body, status_code=413, media_type="application/json")


class LimitRequestBodyMiddleware(BaseHTTPMiddleware):
    """Reject POST/PUT bodies over the configured limit using Content-Length (when present)."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._max_bytes = settings.sparky_max_request_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in frozenset(("POST", "PUT", "PATCH")):
            raw = request.headers.get("content-length")
            if raw is not None:
                try:
                    length = int(raw)
                except ValueError:
                    length = -1
                if length > self._max_bytes:
                    return _payload_too_large_response(self._max_bytes)
        return await call_next(request)
