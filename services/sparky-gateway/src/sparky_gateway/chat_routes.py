"""POST /v1/chat/completions — OpenAI-compatible proxy to the text runtime (PLAN §5.1, §12)."""

from __future__ import annotations

import logging
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import verify_api_key
from .config import Settings
from .errors import envelope
from .registry import Model, Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["text"])


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionRequestBody(BaseModel):
    """Validated gateway view; extra OpenAI fields are forwarded verbatim."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=16384)
    stream: bool | None = None

    @field_validator("stream")
    @classmethod
    def reject_streaming(cls, v: bool | None) -> bool | None:
        if v is True:
            raise ValueError("streaming is not implemented; omit stream or set stream=false")
        return v


def _text_runtime_base_url(settings: Settings, model: Model) -> str:
    if model.runtime_url:
        return str(model.runtime_url).rstrip("/")
    if model.runtime == "trtllm":
        return str(settings.nemotron_trtllm_url).rstrip("/")
    return str(settings.nemotron_vllm_url).rstrip("/")


def _require_approved_text_model(registry: Registry, model_id: str, rid: str | None) -> Model:
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
    if m.family != "text":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                f"model {model_id!r} is not a text runtime model",
                rid,
            ),
        )
    if m.runtime not in ("vllm", "trtllm"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                f"model {model_id!r} must use vllm or trtllm for chat completions",
                rid,
            ),
        )
    return m


@router.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
def chat_completions(
    request: Request,
    body: ChatCompletionRequestBody,
) -> JSONResponse:
    """Forward non-streaming chat to the configured Nemotron runtime (PLAN §2.2, §12)."""
    settings: Settings = request.app.state.settings
    registry: Registry = request.app.state.registry
    rid = getattr(request.state, "request_id", None)

    model = _require_approved_text_model(registry, body.model, rid)
    base = _text_runtime_base_url(settings, model)
    url = urljoin(base + "/", "v1/chat/completions")
    payload = jsonable_encoder(body, exclude_none=True)

    timeout = httpx.Timeout(settings.sparky_request_timeout_seconds)
    try:
        with httpx.Client(timeout=timeout) as client:
            upstream = client.post(url, json=payload)
    except httpx.RequestError as exc:
        log.warning(
            "chat_completions_upstream_unreachable",
            extra={"request_id": rid, "model": body.model, "url": url, "error": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=envelope(
                "runtime_unavailable",
                "text runtime could not be reached; confirm vLLM is listening",
                rid,
            ),
        ) from exc

    ct = upstream.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            data: Any = upstream.json()
        except ValueError:
            data = {"raw": upstream.text}
        return JSONResponse(status_code=upstream.status_code, content=data)
    return JSONResponse(
        status_code=upstream.status_code,
        content={"detail": upstream.text},
    )
