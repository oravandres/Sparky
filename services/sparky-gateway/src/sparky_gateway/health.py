"""Liveness and readiness probes — PLAN.md §5.1, §12."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import APIRouter, Request, Response, status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: cheap, no dependencies."""
    try:
        ver = version("sparky-gateway")
    except PackageNotFoundError:
        ver = "0.0.0"
    return {"status": "ok", "version": ver}


@router.get("/ready")
def ready(request: Request, response: Response) -> dict[str, Any]:
    """Readiness: surfaces dependency status. Phase 3 only checks the registry;
    runtime probes (vLLM, ComfyUI, audio) land in their respective phase PRs."""
    deps: dict[str, dict[str, str]] = {}

    registry = getattr(request.app.state, "registry", None)
    if registry is not None and len(registry.models) > 0:
        deps["model_registry"] = {
            "status": "ready",
            "detail": f"{len(registry.active())} active models",
        }
    else:
        deps["model_registry"] = {"status": "not_ready", "detail": "registry not loaded"}

    overall = "ready" if all(d["status"] == "ready" for d in deps.values()) else "not_ready"
    if overall != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": overall, "dependencies": deps}
