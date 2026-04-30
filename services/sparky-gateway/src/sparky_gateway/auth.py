"""Bearer-token authentication — see PLAN.md §10.

The gateway treats `SPARKY_API_KEY` as a single shared secret mirrored
from MiMi-Secrets. Per-service keys land in a later phase (PLAN §20).
"""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status

from .errors import envelope


def verify_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency. Returns None on success, raises 401 otherwise."""
    settings = request.app.state.settings
    expected_key: str = settings.sparky_api_key
    rid = getattr(request.state, "request_id", None)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=envelope("unauthorized", "Missing or malformed Authorization header", rid),
            headers={"WWW-Authenticate": "Bearer"},
        )

    presented = authorization.removeprefix("Bearer ").strip()
    if not expected_key or not hmac.compare_digest(presented, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=envelope("unauthorized", "Invalid API key", rid),
            headers={"WWW-Authenticate": "Bearer"},
        )
