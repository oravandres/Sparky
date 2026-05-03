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
    """Readiness: surfaces dependency status. Phase 3 only checks the registry
    and the file-backed job ledger; runtime probes (vLLM, ComfyUI, audio) land
    in their respective phase PRs."""
    deps: dict[str, dict[str, str]] = {}

    registry = getattr(request.app.state, "registry", None)
    if registry is None:
        deps["model_registry"] = {"status": "not_ready", "detail": "registry not loaded"}
    else:
        active = registry.active()
        if len(active) > 0:
            deps["model_registry"] = {
                "status": "ready",
                "detail": f"{len(active)} active models",
            }
        else:
            deps["model_registry"] = {
                "status": "not_ready",
                "detail": "no active models in registry",
            }

    # Jobs ledger (PLAN §18). Boot stays decoupled from the volume mount; we
    # only flag readiness here so MiMi monitoring sees the misconfiguration
    # before a media submission turns into a 503.
    job_store = getattr(request.app.state, "job_store", None)
    if job_store is None:
        deps["jobs_dir"] = {"status": "not_ready", "detail": "job store not loaded"}
    elif job_store.is_writable():
        deps["jobs_dir"] = {
            "status": "ready",
            "detail": str(job_store.jobs_dir),
        }
    else:
        deps["jobs_dir"] = {
            "status": "not_ready",
            "detail": (
                f"jobs_dir {job_store.jobs_dir!s} missing or not writable; "
                "media/audio submissions will return 503"
            ),
        }

    overall = "ready" if all(d["status"] == "ready" for d in deps.values()) else "not_ready"
    if overall != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": overall, "dependencies": deps}
