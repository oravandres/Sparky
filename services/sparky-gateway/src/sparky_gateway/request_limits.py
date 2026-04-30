"""ASGI middleware — bounded request bodies for mutating methods (PLAN §12).

Rejects requests early when ``Content-Length`` exceeds the cap (covers chunked
declarations without buffering the entity). Otherwise reads the full body via
Starlette (bounded in practice when the length header is accurate) and returns
413 before application JSON parsing when the cap is exceeded. Pair with a
front proxy ``client_max_body_size`` (or equivalent) to hard-limit dishonest
length headers or pathological slowlorries.
"""

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
    """Buffer POST/PUT/PATCH bodies up to the configured cap, then replay to the app."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._max_bytes = settings.sparky_max_request_body_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in ("POST", "PUT", "PATCH"):
            return await call_next(request)

        raw_cl = request.headers.get("content-length")
        if raw_cl is not None:
            try:
                declared = int(raw_cl)
            except ValueError:
                pass
            else:
                if declared > self._max_bytes:
                    return _payload_too_large_response(self._max_bytes)

        body = await request.body()
        if len(body) > self._max_bytes:
            return _payload_too_large_response(self._max_bytes)

        sent = False

        async def receive_replay() -> dict[str, str | bytes | bool]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        replayed = Request(request.scope, receive_replay)
        return await call_next(replayed)
