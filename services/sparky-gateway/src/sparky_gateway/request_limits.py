"""ASGI-level request body cap (PLAN §12).

Reads the HTTP entity in ``receive`` chunks, returns 413 as soon as accumulated
bytes exceed the configured maximum, then replays a single buffered body to the
inner application. Honest oversize ``Content-Length`` is rejected without
buffering the entity; chunked or missing length uses incremental accounting so
the cap applies before the full body is materialized.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI
from starlette.types import Receive, Scope, Send


def _content_length(scope: Scope) -> int | None:
    for key, value in scope.get("headers", []):
        if key == b"content-length":
            try:
                return int(value.decode("latin1"))
            except ValueError:
                return None
    return None


async def _send_413(send: Send, max_bytes: int) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "payload_too_large",
                "message": f"request body exceeds {max_bytes} bytes",
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitASGI:
    """Outermost ASGI wrapper: enforce ``max_bytes`` while reading the request body."""

    __slots__ = ("_app", "_max_bytes")

    def __init__(self, app: FastAPI, max_bytes: int) -> None:
        self._app: FastAPI = app
        self._max_bytes = max_bytes

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access so callers can treat this like the wrapped FastAPI app."""
        return getattr(self._app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "")
        if method not in ("POST", "PUT", "PATCH"):
            await self._app(scope, receive, send)
            return

        cl = _content_length(scope)
        if cl is not None and cl > self._max_bytes:
            await _send_413(send, self._max_bytes)
            return

        body_parts: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            next_total = total + len(chunk)
            if next_total > self._max_bytes:
                await _send_413(send, self._max_bytes)
                return
            total = next_total
            body_parts.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(body_parts)
        sent = False

        async def receive_replay() -> dict[str, Any]:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self._app(scope, receive_replay, send)
