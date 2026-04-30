"""POST /v1/chat/completions — OpenAI-compatible proxy to the text runtime (PLAN §5.1, §12)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import verify_api_key
from .config import Settings
from .errors import envelope
from .registry import Model, Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["text"])

# Parser hard caps — operator-tunable limits are enforced again in the handler using Settings.
_HARD_MAX_MESSAGES = 128
_PARSER_MAX_CONTENT_CHARS = 1_000_000


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(
        min_length=1,
        max_length=_PARSER_MAX_CONTENT_CHARS,
    )


class ChatCompletionRequestBody(BaseModel):
    """Whitelisted OpenAI/vLLM fields only — unknown keys are rejected (422)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=_HARD_MAX_MESSAGES)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=16384)
    top_p: float | None = Field(default=None, ge=0, le=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    stop: str | list[str] | None = None
    user: str | None = Field(default=None, max_length=256)
    stream: bool | None = None

    @field_validator("stream")
    @classmethod
    def reject_streaming(cls, v: bool | None) -> bool | None:
        if v is True:
            raise ValueError("streaming is not implemented; omit stream or set stream=false")
        return v

    @field_validator("stop")
    @classmethod
    def limit_stop_sequences(cls, v: str | list[str] | None) -> str | list[str] | None:
        if v is None:
            return None
        parts: list[str] = [v] if isinstance(v, str) else list(v)
        if len(parts) > 4:
            raise ValueError("at most 4 stop sequences are allowed")
        for p in parts:
            if len(p) > 256:
                raise ValueError("each stop sequence must be at most 256 characters")
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


def _enforced_message_policy(
    body: ChatCompletionRequestBody,
    settings: Settings,
    rid: str | None,
) -> None:
    if len(body.messages) > settings.sparky_chat_max_messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_request",
                f"at most {settings.sparky_chat_max_messages} messages are allowed",
                rid,
            ),
        )
    for i, msg in enumerate(body.messages):
        if len(msg.content) > settings.sparky_chat_max_content_chars:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=envelope(
                    "invalid_request",
                    f"message {i} exceeds {settings.sparky_chat_max_content_chars} characters",
                    rid,
                ),
            )


def _completion_payload(body: ChatCompletionRequestBody) -> dict[str, Any]:
    """Forward unknown fields is forbidden — only explicitly listed keys reach vLLM."""
    out: dict[str, Any] = {
        "model": body.model,
        "messages": [{"role": m.role, "content": m.content} for m in body.messages],
    }
    if body.temperature is not None:
        out["temperature"] = body.temperature
    if body.max_tokens is not None:
        out["max_tokens"] = body.max_tokens
    if body.top_p is not None:
        out["top_p"] = body.top_p
    if body.frequency_penalty is not None:
        out["frequency_penalty"] = body.frequency_penalty
    if body.presence_penalty is not None:
        out["presence_penalty"] = body.presence_penalty
    if body.stop is not None:
        out["stop"] = body.stop
    if body.user is not None:
        out["user"] = body.user
    if body.stream is False:
        out["stream"] = False
    return out


@router.post("/v1/chat/completions", dependencies=[Depends(verify_api_key)])
async def chat_completions(
    request: Request,
    body: ChatCompletionRequestBody,
) -> JSONResponse:
    """Forward non-streaming chat to the configured Nemotron runtime (PLAN §2.2, §12)."""
    settings: Settings = request.app.state.settings
    registry: Registry = request.app.state.registry
    rid = getattr(request.state, "request_id", None)
    _enforced_message_policy(body, settings, rid)

    model = _require_approved_text_model(registry, body.model, rid)
    base = _text_runtime_base_url(settings, model)
    url = urljoin(base + "/", "v1/chat/completions")
    payload = _completion_payload(body)

    client: httpx.AsyncClient = request.app.state.http_client
    sem: asyncio.Semaphore = request.app.state.nemotron_sem

    async with sem:
        try:
            upstream = await client.post(url, json=payload)
        except httpx.RequestError as exc:
            log.warning(
                "chat_completions_upstream_unreachable",
                extra={
                    "request_id": rid,
                    "model": body.model,
                    "url": url,
                    "error": type(exc).__name__,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=envelope(
                    "runtime_unavailable",
                    "text runtime could not be reached; confirm vLLM is listening",
                    rid,
                ),
            ) from exc
        except asyncio.CancelledError:
            log.info(
                "chat_completions_cancelled",
                extra={"request_id": rid, "model": body.model},
            )
            raise

    if upstream.status_code < 200 or upstream.status_code >= 300:
        snippet = (upstream.text or "")[:500].replace("\n", " ").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        log.warning(
            "chat_completions_upstream_error",
            extra={
                "request_id": rid,
                "upstream_status": upstream.status_code,
                "upstream_snippet": snippet,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned an error; consult gateway logs using request_id",
                rid,
            ),
        )

    ct = upstream.headers.get("content-type", "")
    if "application/json" not in ct:
        log.warning(
            "chat_completions_upstream_non_json",
            extra={
                "request_id": rid,
                "content_type": ct,
                "upstream_snippet": (upstream.text or "")[:200],
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned a non-JSON response",
                rid,
            ),
        )

    try:
        data: Any = upstream.json()
    except ValueError:
        log.warning(
            "chat_completions_upstream_invalid_json",
            extra={"request_id": rid},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned invalid JSON",
                rid,
            ),
        ) from None

    return JSONResponse(status_code=200, content=data)
