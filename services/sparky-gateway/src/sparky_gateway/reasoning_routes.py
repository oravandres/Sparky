"""POST /v1/reasoning/* — structured analysis via Nemotron (PLAN §5.2, §12).

Builds constrained prompts, proxies to the configured text runtime chat
endpoint, parses model JSON output, and validates against the PLAN contract.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .auth import verify_api_key
from .chat_routes import _require_approved_text_model, _text_runtime_base_url
from .config import Settings
from .errors import envelope
from .registry import Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["reasoning"])

_MAX_TASK_CHARS = 48_000
_MAX_CONTEXT_CHARS = 120_000
_MAX_CRITERIA = 64
_MAX_STRING_PER_LIST = 4_096
_MAX_OPTIONS = 24
_MAX_COMPARE_CRITERIA = 32
_MAX_CONSTRAINTS = 64


class ReasoningAnalyzeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    task: str = Field(min_length=1, max_length=_MAX_TASK_CHARS)
    context: str | None = Field(default=None, max_length=_MAX_CONTEXT_CHARS)
    criteria: list[str] = Field(default_factory=list, max_length=_MAX_CRITERIA)
    output_style: Literal["structured", "prose", "bulleted"] | None = None
    max_tokens: int = Field(default=2048, ge=1, le=16384)

    @field_validator("criteria")
    @classmethod
    def _criteria_items(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > _MAX_STRING_PER_LIST:
                raise ValueError(f"criteria[{i}] exceeds {_MAX_STRING_PER_LIST} characters")
        return v


class ReasoningAnalyzeResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    summary: str
    key_points: list[str]
    risks: list[str]
    assumptions: list[str]
    recommendation: str
    confidence: Literal["high", "medium", "low"]


class CompareOptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=512)
    description: str | None = Field(default=None, max_length=8_000)


class CompareCriterionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=512)
    weight: float = Field(default=1.0, ge=0.0, le=100.0)


class ReasoningCompareRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    question: str = Field(min_length=1, max_length=_MAX_TASK_CHARS)
    options: list[CompareOptionIn] = Field(min_length=1, max_length=_MAX_OPTIONS)
    criteria: list[CompareCriterionIn] = Field(
        min_length=1,
        max_length=_MAX_COMPARE_CRITERIA,
    )
    constraints: list[str] = Field(default_factory=list, max_length=_MAX_CONSTRAINTS)

    @field_validator("constraints")
    @classmethod
    def _constraints_items(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > _MAX_STRING_PER_LIST:
                raise ValueError(f"constraints[{i}] exceeds {_MAX_STRING_PER_LIST} characters")
        return v


class CompareScoreOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    criterion_id: str
    score: float = Field(ge=0.0, le=10.0)
    rationale: str


class CompareTotalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    weighted_total: float


class CompareRecommendationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str
    reasoning: str
    caveats: list[str] = Field(default_factory=list)


class ReasoningCompareResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: list[CompareScoreOut]
    totals: list[CompareTotalOut]
    recommendation: CompareRecommendationOut
    confidence: Literal["high", "medium", "low"]


def _strip_json_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, count=1, flags=re.IGNORECASE)
        s = re.sub(r"\s*```\s*$", "", s, count=1, flags=re.IGNORECASE)
    return s.strip()


def _openai_choice_text(completion: dict[str, Any]) -> str | None:
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    msg = first.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def _analyze_system_prompt() -> str:
    return (
        "You are Sparky's structured reasoning engine. Respond with ONLY a single "
        "JSON object (no markdown fences, no commentary) with exactly these keys: "
        '"summary" (string), "key_points" (array of strings), "risks" (array of '
        'strings), "assumptions" (array of strings), "recommendation" (string), '
        '"confidence" (one of: high, medium, low). Follow the user instructions '
        "for tone and structure (structured, prose, or bulleted) inside those "
        "string fields."
    )


def _analyze_user_payload(body: ReasoningAnalyzeRequestBody) -> str:
    payload = {
        "task": body.task,
        "context": body.context,
        "criteria": body.criteria,
        "output_style": body.output_style or "structured",
    }
    return (
        "Analyze the following request. Return JSON only as specified in your "
        "system message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _compare_system_prompt() -> str:
    return (
        "You are Sparky's structured comparison engine. Respond with ONLY a single "
        "JSON object (no markdown fences, no commentary) with keys: "
        '"scores" (array of {option_id, criterion_id, score, rationale}), '
        '"totals" (array of {option_id, weighted_total}), '
        '"recommendation" (object with option_id, reasoning, and optional caveats '
        "array of strings), "
        '"confidence" (high, medium, or low). '
        "Scores must be numeric in [0, 10] for each option-criterion pair. "
        "Include exactly one score entry for every requested option id and criterion id. "
        "The gateway validates coverage and recomputes weighted_totals from scores "
        "and criterion weights."
    )


def _compare_user_payload(body: ReasoningCompareRequestBody) -> str:
    payload = {
        "question": body.question,
        "options": [o.model_dump(exclude_none=True) for o in body.options],
        "criteria": [c.model_dump() for c in body.criteria],
        "constraints": body.constraints,
    }
    return (
        "Compare the options. Return JSON only as specified in your system message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


async def _post_upstream_chat(
    request: Request,
    *,
    model_id: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
    rid: str | None,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    registry: Registry = request.app.state.registry
    model = _require_approved_text_model(registry, model_id, rid)
    base = _text_runtime_base_url(settings, model)
    url = urljoin(base + "/", "v1/chat/completions")
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    client: httpx.AsyncClient = request.app.state.http_client
    sem: asyncio.Semaphore = request.app.state.nemotron_sem

    async with sem:
        try:
            upstream = await client.post(url, json=payload)
        except httpx.RequestError as exc:
            log.warning(
                "reasoning_upstream_unreachable",
                extra={
                    "request_id": rid,
                    "model": model_id,
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
            log.info("reasoning_upstream_cancelled", extra={"request_id": rid})
            raise

    if upstream.status_code < 200 or upstream.status_code >= 300:
        log.warning(
            "reasoning_upstream_error",
            extra={
                "request_id": rid,
                "upstream_status": upstream.status_code,
                "upstream_content_type": upstream.headers.get("content-type", ""),
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
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned invalid JSON",
                rid,
            ),
        ) from None

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned an unexpected completion shape",
                rid,
            ),
        )
    return data


def _parse_model_json(completion: dict[str, Any], rid: str | None, model_id: str) -> dict[str, Any]:
    raw = _openai_choice_text(completion)
    if raw is None:
        log.warning(
            "reasoning_model_empty_content",
            extra={"request_id": rid, "model": model_id},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned no assistant message content",
                rid,
            ),
        )
    try:
        return json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        log.warning(
            "reasoning_model_invalid_json",
            extra={"request_id": rid, "model": model_id, "error": "JSONDecodeError"},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime did not return valid JSON for reasoning output",
                rid,
            ),
        ) from None


def _finalize_compare_response(
    body: ReasoningCompareRequestBody,
    out: ReasoningCompareResponseBody,
    *,
    rid: str | None,
    model_id: str,
) -> ReasoningCompareResponseBody:
    """Ensure scores reference the caller payload and totals match weights."""

    opt_ids = {o.id for o in body.options}
    crit_weights = {c.id: float(c.weight) for c in body.criteria}
    expected_pairs = {(oid, cid) for oid in opt_ids for cid in crit_weights}

    by_pair: dict[tuple[str, str], CompareScoreOut] = {}
    for row in out.scores:
        if row.option_id not in opt_ids or row.criterion_id not in crit_weights:
            log.warning(
                "reasoning_compare_unknown_ids",
                extra={
                    "request_id": rid,
                    "model": model_id,
                    "option_id": row.option_id,
                    "criterion_id": row.criterion_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=envelope(
                    "runtime_error",
                    "text runtime emitted scores outside the supplied options or criteria",
                    rid,
                ),
            )
        key = (row.option_id, row.criterion_id)
        if key in by_pair:
            log.warning(
                "reasoning_compare_duplicate_score",
                extra={
                    "request_id": rid,
                    "model": model_id,
                    "option_id": row.option_id,
                    "criterion_id": row.criterion_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=envelope(
                    "runtime_error",
                    "text runtime emitted duplicate scores for an option–criterion pair",
                    rid,
                ),
            )
        by_pair[key] = row

    if set(by_pair.keys()) != expected_pairs:
        log.warning(
            "reasoning_compare_incomplete_scores",
            extra={
                "request_id": rid,
                "model": model_id,
                "expected_pairs": len(expected_pairs),
                "received_pairs": len(by_pair),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime omitted scores for required option–criterion pairs",
                rid,
            ),
        )

    if out.recommendation.option_id not in opt_ids:
        log.warning(
            "reasoning_compare_bad_recommendation",
            extra={
                "request_id": rid,
                "model": model_id,
                "option_id": out.recommendation.option_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime recommended an option id that was not in the request",
                rid,
            ),
        )

    totals_list = [
        CompareTotalOut(
            option_id=oid,
            weighted_total=sum(
                by_pair[(oid, cid)].score * crit_weights[cid] for cid in crit_weights
            ),
        )
        for oid in sorted(opt_ids)
    ]

    return ReasoningCompareResponseBody(
        scores=out.scores,
        totals=totals_list,
        recommendation=out.recommendation,
        confidence=out.confidence,
    )


@router.post("/v1/reasoning/analyze", dependencies=[Depends(verify_api_key)])
async def reasoning_analyze(
    request: Request,
    body: ReasoningAnalyzeRequestBody,
) -> JSONResponse:
    """Single-input deep analysis (PLAN §5.2.1)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_reasoning_model_id

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_analyze_system_prompt(),
        user_content=_analyze_user_payload(body),
        max_tokens=body.max_tokens,
        temperature=settings.sparky_reasoning_temperature,
        rid=rid,
    )
    parsed_obj = _parse_model_json(completion, rid, model_id)
    try:
        out = ReasoningAnalyzeResponseBody.model_validate(parsed_obj)
    except ValidationError as exc:
        log.warning(
            "reasoning_model_schema_mismatch",
            extra={
                "request_id": rid,
                "model": model_id,
                "endpoint": "analyze",
                "error": exc.__class__.__name__,
                "validation_errors": len(exc.errors()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime JSON did not match the reasoning analyze schema",
                rid,
            ),
        ) from None
    return JSONResponse(status_code=200, content=out.model_dump())


@router.post("/v1/reasoning/compare", dependencies=[Depends(verify_api_key)])
async def reasoning_compare(
    request: Request,
    body: ReasoningCompareRequestBody,
) -> JSONResponse:
    """Side-by-side option comparison (PLAN §5.2.2)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_reasoning_model_id
    mt = settings.sparky_reasoning_compare_max_tokens

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_compare_system_prompt(),
        user_content=_compare_user_payload(body),
        max_tokens=mt,
        temperature=settings.sparky_reasoning_temperature,
        rid=rid,
    )
    parsed_obj = _parse_model_json(completion, rid, model_id)
    try:
        out = ReasoningCompareResponseBody.model_validate(parsed_obj)
    except ValidationError as exc:
        log.warning(
            "reasoning_model_schema_mismatch",
            extra={
                "request_id": rid,
                "model": model_id,
                "endpoint": "compare",
                "error": exc.__class__.__name__,
                "validation_errors": len(exc.errors()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime JSON did not match the reasoning compare schema",
                rid,
            ),
        ) from None
    final_out = _finalize_compare_response(body, out, rid=rid, model_id=model_id)
    return JSONResponse(status_code=200, content=final_out.model_dump())
