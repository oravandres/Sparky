"""GET /v1/jobs/{job_id} and POST /v1/jobs/{job_id}/cancel — shared job control (PLAN §5.7, §18).

Job records are written by the media (and audio, in a follow-up PR) submission
routes via :class:`~sparky_gateway.job_store.JobStore` and consumed here.
PLAN §5.7 carves out one shared set of control endpoints for every async job
type (image / video / tts / asr) so consumers don't need a per-family
polling surface.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .auth import verify_api_key
from .errors import envelope
from .job_store import (
    JobConflictError,
    JobNotFoundError,
    JobStore,
    is_valid_job_id,
)

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["jobs"])


def _job_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Project the persisted record onto the public ``Job`` envelope (api-contract.yaml)."""
    return {k: v for k, v in record.items() if k != "request" and v is not None}


@router.get("/v1/jobs/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_job(request: Request, job_id: str) -> JSONResponse:
    """Return the current job record (PLAN §18)."""
    rid = getattr(request.state, "request_id", None)
    if not is_valid_job_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=envelope("not_found", f"no job with id {job_id!r}", rid),
        )

    store: JobStore = request.app.state.job_store
    try:
        record = await store.get(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=envelope("not_found", str(exc), rid),
        ) from exc
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_job_payload(record.model_dump()),
    )


@router.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_job(request: Request, job_id: str) -> JSONResponse:
    """Cancel a non-terminal job; idempotent against an already-cancelled job (PLAN §18)."""
    rid = getattr(request.state, "request_id", None)
    if not is_valid_job_id(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=envelope("not_found", f"no job with id {job_id!r}", rid),
        )

    store: JobStore = request.app.state.job_store
    try:
        record = await store.cancel(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=envelope("not_found", str(exc), rid),
        ) from exc
    except JobConflictError as exc:
        # Cancelling a completed/failed job is a 409: callers see that the
        # job already reached a terminal state and they should fetch the
        # record instead of retrying cancel.
        log.info(
            "job_cancel_conflict",
            extra={"request_id": rid, "job_id": job_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=envelope("job_terminal", str(exc), rid),
        ) from exc
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=_job_payload(record.model_dump()),
    )
