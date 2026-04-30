"""GET /v1/models — see PLAN.md §5.1, §7.3, §4.3 (state field)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from .auth import verify_api_key

router = APIRouter(tags=["models"])


@router.get("/v1/models", dependencies=[Depends(verify_api_key)])
def list_models(request: Request) -> dict[str, Any]:
    """Return active models with co-residency state.

    Phase 3 returns `state: "cold"` uniformly. The worker (PLAN §4.3) will
    update this to hot|cold|loading|evicting once runtime tracking lands.
    """
    registry = request.app.state.registry
    return {
        "data": [
            {
                "id": m.id,
                "family": m.family,
                "role": m.role,
                "tier": m.tier,
                "runtime": m.runtime,
                "revision": m.revision,
                "priority": m.priority,
                "active": m.active,
                "state": "cold",
            }
            for m in registry.active()
        ]
    }
