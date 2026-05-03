"""POST /v1/media/{image,video}/jobs — image and video job submission (PLAN §5.5, §16, §18).

Phase 7 (gateway side): callers submit a job describing an approved image or
video model and the gateway returns ``202`` with ``{job_id, type, "queued"}``.
The actual ComfyUI work is performed by ``services/sparky-worker`` (PLAN
§7.2) which polls the on-disk job ledger written here. This module never
talks to ComfyUI directly — that keeps the gateway thin per
``AGENTS.md`` and PLAN §4.3.

Validation responsibilities (mirror ``config/api-contract.yaml`` ImageJobRequest /
VideoJobRequest):

* ``model`` must reference an *active* registry entry whose ``family`` matches
  the route (``image`` or ``video``) and whose ``runtime`` is ``comfyui`` —
  the gateway must not silently substitute another approved model (PLAN §2.2).
* image: width/height (multiple of 64), steps, seed bounds.
* video: duration/fps/resolution caps **plus** the
  ``max_frames == ceil(duration_seconds × fps)`` and
  ``max_pixel_frames == max_frames × width × height`` cross-checks.
  Sending mismatched values returns 422 before enqueue so an oversized job
  cannot consume the single-slot media tier (PLAN §4.3 Tier B).
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import verify_api_key
from .errors import envelope
from .job_store import JobStore, JobType
from .registry import Model, Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["media"])

# Hard caps mirror config/api-contract.yaml. Pydantic enforces them with
# explicit error envelopes; CI lints both files for drift (PLAN §22).
_PROMPT_MAX_CHARS = 32_000

ImageModelId = Literal["flux2-dev", "flux2-klein", "qwen-image", "hunyuanimage-3-instruct"]
VideoModelId = Literal["ltx-2", "wan-2.2", "hunyuanvideo-1.5"]


class ImageJobRequestBody(BaseModel):
    """Image job submission shape (PLAN §16 / api-contract.yaml ImageJobRequest)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model: ImageModelId
    prompt: str = Field(min_length=1, max_length=_PROMPT_MAX_CHARS)
    negative_prompt: str | None = Field(default=None, max_length=_PROMPT_MAX_CHARS)
    width: int = Field(default=1024, ge=256, le=4096)
    height: int = Field(default=1024, ge=256, le=4096)
    steps: int = Field(default=30, ge=1, le=150)
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _alignment(self) -> ImageJobRequestBody:
        if self.width % 64 != 0:
            raise ValueError("width must be a multiple of 64")
        if self.height % 64 != 0:
            raise ValueError("height must be a multiple of 64")
        return self


class VideoJobRequestBody(BaseModel):
    """Video job submission shape (PLAN §16 / api-contract.yaml VideoJobRequest)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model: VideoModelId
    prompt: str = Field(min_length=1, max_length=_PROMPT_MAX_CHARS)
    duration_seconds: int = Field(default=5, ge=1, le=12)
    width: int = Field(default=1280, ge=256, le=1280)
    height: int = Field(default=720, ge=256, le=720)
    fps: int = Field(default=24, ge=1, le=24)
    max_frames: int = Field(ge=1, le=288)
    max_pixel_frames: int = Field(ge=1, le=265_420_800)
    seed: int | None = Field(default=None, ge=0, le=4_294_967_295)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _alignment_and_budget(self) -> VideoJobRequestBody:
        if self.width % 16 != 0:
            raise ValueError("width must be a multiple of 16")
        if self.height % 16 != 0:
            raise ValueError("height must be a multiple of 16")
        # Phase 1 contract: max_frames must equal ceil(duration_seconds × fps),
        # and max_pixel_frames must equal that frame count × width × height.
        # Mismatched values fail the contract (PLAN §16) before enqueue.
        expected_frames = math.ceil(self.duration_seconds * self.fps)
        if self.max_frames != expected_frames:
            raise ValueError(
                "max_frames must equal ceil(duration_seconds × fps); "
                f"expected {expected_frames}, got {self.max_frames}"
            )
        expected_pixels = expected_frames * self.width * self.height
        if self.max_pixel_frames != expected_pixels:
            raise ValueError(
                "max_pixel_frames must equal max_frames × width × height; "
                f"expected {expected_pixels}, got {self.max_pixel_frames}"
            )
        return self


def _require_media_model(
    registry: Registry,
    *,
    model_id: str,
    expected_family: Literal["image", "video"],
    rid: str | None,
) -> Model:
    """Resolve ``model_id`` against the registry and enforce route invariants."""
    m = registry.by_id(model_id)
    if m is None or not m.active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "unapproved_model",
                f"model {model_id!r} is not an active entry in the Sparky registry",
                rid,
            ),
        )
    if m.family != expected_family:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                (
                    f"model {model_id!r} (family={m.family!r}) is not valid for "
                    f"the {expected_family} jobs endpoint"
                ),
                rid,
            ),
        )
    if m.runtime != "comfyui":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                f"model {model_id!r} must use the comfyui runtime for media jobs",
                rid,
            ),
        )
    return m


def _accepted_payload(*, job_id: str, job_type: JobType) -> dict[str, str]:
    """Stable JobAccepted envelope (PLAN §5.7, OpenAPI ``JobAccepted``)."""
    return {"job_id": job_id, "type": job_type, "status": "queued"}


@router.post(
    "/v1/media/image/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def submit_image_job(
    request: Request,
    body: ImageJobRequestBody,
) -> JSONResponse:
    """Submit an image generation job (PLAN §5.5, §16)."""
    rid = getattr(request.state, "request_id", None)
    registry: Registry = request.app.state.registry
    _require_media_model(registry, model_id=body.model, expected_family="image", rid=rid)

    store: JobStore = request.app.state.job_store
    record = await store.create(
        job_type="image",
        model=body.model,
        request=body.model_dump(exclude_none=True),
    )
    log.info(
        "media_image_job_accepted",
        extra={"request_id": rid, "job_id": record.job_id, "model": body.model},
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=_accepted_payload(job_id=record.job_id, job_type="image"),
    )


@router.post(
    "/v1/media/video/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def submit_video_job(
    request: Request,
    body: VideoJobRequestBody,
) -> JSONResponse:
    """Submit a video generation job (PLAN §5.5, §16)."""
    rid = getattr(request.state, "request_id", None)
    registry: Registry = request.app.state.registry
    _require_media_model(registry, model_id=body.model, expected_family="video", rid=rid)

    store: JobStore = request.app.state.job_store
    record = await store.create(
        job_type="video",
        model=body.model,
        request=body.model_dump(exclude_none=True),
    )
    log.info(
        "media_video_job_accepted",
        extra={"request_id": rid, "job_id": record.job_id, "model": body.model},
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=_accepted_payload(job_id=record.job_id, job_type="video"),
    )
