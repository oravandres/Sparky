"""POST /v1/coding/* — Sparky's coding intelligence (PLAN §5.4, §15).

Four routes share one request/response shape — PLAN §15 and
``config/api-contract.yaml`` intentionally model them against a single
``CodingReviewRequest`` / ``CodingReviewResponse`` pair. The differences
between them are only the ``task`` (and therefore the system prompt
guidance) and the route path Maestro / PR-review agents hit:

    /review            → review, debug
    /architecture      → architecture
    /refactor-plan     → refactor-plan
    /security-review   → security-review

Each handler:

  1. Validates the caller payload (Pydantic, ``extra='forbid'``) with
     per-field size caps and an aggregate character budget that stays
     comfortably below the gateway's body limit.
  2. Builds a constrained system + user prompt that instructs Nemotron
     to emit ONLY a single JSON object matching the schema in §15.
  3. Proxies through the already-throttled Nemotron semaphore / HTTP
     client, same as the reasoning and agentic-rag modules.
  4. Parses and validates the model JSON against a strict Pydantic
     response schema; any schema drift returns HTTP 502.
  5. Applies integrity checks the model cannot be trusted with:
       - finding ``path`` values must reference a supplied file when
         the caller gave us files, so the reviewer cannot cite paths
         that do not exist in the submitted snapshot;
       - finding ``line`` must be inside the referenced file's line
         count;
       - ``final_recommendation="approve"`` is not allowed while at
         least one ``critical`` finding is present — that mirrors the
         PLAN §14 / §15 quality rule that critical issues must not
         be silently approved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Literal, cast
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .auth import verify_api_key
from .chat_routes import _require_approved_text_model, _text_runtime_base_url
from .config import Settings
from .errors import envelope
from .registry import Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["coding"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

# Per-field bounds. Caller payloads are already capped by BodySizeLimitASGI
# (default 2 MiB). These per-field caps plus the aggregate check below make
# prompt size predictable without ever reading the whole body into memory to
# measure it.
_MAX_REPOSITORY_CHARS = 512
_MAX_INSTRUCTIONS_CHARS = 16_000
_MAX_PATH_CHARS = 4_096
_MAX_FILE_CONTENT_CHARS = 200_000
_MAX_DIFF_CHARS = 500_000
_HARD_MAX_FILES = 256
_HARD_MAX_TOTAL_INPUT_CHARS = 1_500_000

_FINDING_PATH_MAX = 4_096
_FINDING_TITLE_MAX = 512
_FINDING_EXPLANATION_MAX = 8_000
_FINDING_RECOMMENDATION_MAX = 8_000
_SUMMARY_MAX = 16_000
_ARCH_NOTE_MAX = 4_096
_TEST_NOTE_MAX = 4_096

CodingTask = Literal[
    "review",
    "architecture",
    "debug",
    "refactor-plan",
    "security-review",
]

CodingLanguage = Literal["go", "typescript", "python", "yaml", "mixed"]


class CodingFileIn(BaseModel):
    """One file snapshot the reviewer should consider (PLAN §15)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    path: str = Field(min_length=1, max_length=_MAX_PATH_CHARS)
    content: str = Field(min_length=1, max_length=_MAX_FILE_CONTENT_CHARS)


class CodingReviewRequestBody(BaseModel):
    """PLAN §15 request envelope, shared by all four routes."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    task: CodingTask
    repository: str | None = Field(default=None, max_length=_MAX_REPOSITORY_CHARS)
    language: CodingLanguage | None = None
    files: list[CodingFileIn] = Field(default_factory=list, max_length=_HARD_MAX_FILES)
    diff: str | None = Field(default=None, max_length=_MAX_DIFF_CHARS)
    instructions: str | None = Field(default=None, max_length=_MAX_INSTRUCTIONS_CHARS)
    max_tokens: int | None = Field(default=None, ge=1, le=16384)

    @field_validator("files")
    @classmethod
    def _unique_file_paths(cls, v: list[CodingFileIn]) -> list[CodingFileIn]:
        seen: set[str] = set()
        for f in v:
            if f.path in seen:
                raise ValueError(f"files[].path must be unique; duplicated {f.path!r}")
            seen.add(f.path)
        return v

    @model_validator(mode="after")
    def _require_something_to_review(self) -> CodingReviewRequestBody:
        if not self.files and not (self.diff and self.diff.strip()):
            if not (self.instructions and self.instructions.strip()):
                raise ValueError("at least one of files, diff, or instructions must be provided")
        total = sum(len(f.content) for f in self.files)
        total += len(self.diff or "")
        total += len(self.instructions or "")
        if total > _HARD_MAX_TOTAL_INPUT_CHARS:
            raise ValueError(
                f"aggregate input (files + diff + instructions) exceeds "
                f"{_HARD_MAX_TOTAL_INPUT_CHARS} characters"
            )
        return self


class CodingFindingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["critical", "high", "medium", "low", "nit"]
    path: str | None = Field(default=None, max_length=_FINDING_PATH_MAX)
    line: int | None = Field(default=None, ge=1, le=10_000_000)
    title: str = Field(min_length=1, max_length=_FINDING_TITLE_MAX)
    explanation: str = Field(min_length=1, max_length=_FINDING_EXPLANATION_MAX)
    recommendation: str = Field(min_length=1, max_length=_FINDING_RECOMMENDATION_MAX)


class CodingReviewResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=_SUMMARY_MAX)
    findings: list[CodingFindingOut] = Field(default_factory=list)
    architecture_notes: list[str] = Field(default_factory=list)
    tests_to_add: list[str] = Field(default_factory=list)
    final_recommendation: Literal["approve", "request_changes", "needs_human_review"]

    @field_validator("architecture_notes")
    @classmethod
    def _arch_note_items(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > _ARCH_NOTE_MAX:
                raise ValueError(f"architecture_notes[{i}] exceeds {_ARCH_NOTE_MAX} characters")
        return v

    @field_validator("tests_to_add")
    @classmethod
    def _test_note_items(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > _TEST_NOTE_MAX:
                raise ValueError(f"tests_to_add[{i}] exceeds {_TEST_NOTE_MAX} characters")
        return v


# ---------------------------------------------------------------------------
# Route → allowed task(s) mapping (PLAN §15)
# ---------------------------------------------------------------------------

# /review is the general-purpose route; PLAN §15 lists "debug" as a task
# value but does not carve out a /debug endpoint, so debug reviews go here.
_REVIEW_TASKS: frozenset[CodingTask] = frozenset({"review", "debug"})
_ARCHITECTURE_TASKS: frozenset[CodingTask] = frozenset({"architecture"})
_REFACTOR_TASKS: frozenset[CodingTask] = frozenset({"refactor-plan"})
_SECURITY_TASKS: frozenset[CodingTask] = frozenset({"security-review"})


def _require_task(
    body: CodingReviewRequestBody,
    allowed: frozenset[CodingTask],
    rid: str | None,
) -> None:
    if body.task not in allowed:
        allowed_list = sorted(allowed)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_request",
                f"task {body.task!r} is not valid for this route; expected one of {allowed_list}",
                rid,
            ),
        )


# ---------------------------------------------------------------------------
# Upstream helpers (mirror reasoning_routes / agentic_rag_routes to keep
# this PR self-contained; extraction is intentionally deferred until a
# third consumer lands and a shared module is clearly worth the churn).
# ---------------------------------------------------------------------------


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


async def _post_upstream_chat(
    request: Request,
    *,
    model_id: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
    temperature: float,
    rid: str | None,
    task: CodingTask,
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
                "coding_upstream_unreachable",
                extra={
                    "request_id": rid,
                    "task": task,
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
            log.info(
                "coding_upstream_cancelled",
                extra={"request_id": rid, "task": task},
            )
            raise

    if upstream.status_code < 200 or upstream.status_code >= 300:
        log.warning(
            "coding_upstream_error",
            extra={
                "request_id": rid,
                "task": task,
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


def _parse_model_json(
    completion: dict[str, Any],
    rid: str | None,
    model_id: str,
    task: CodingTask,
) -> dict[str, Any]:
    raw = _openai_choice_text(completion)
    if raw is None:
        log.warning(
            "coding_model_empty_content",
            extra={"request_id": rid, "model": model_id, "task": task},
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
        loaded: Any = json.loads(_strip_json_fences(raw))
    except json.JSONDecodeError:
        log.warning(
            "coding_model_invalid_json",
            extra={"request_id": rid, "model": model_id, "task": task},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime did not return valid JSON for coding output",
                rid,
            ),
        ) from None
    if not isinstance(loaded, dict):
        log.warning(
            "coding_model_json_not_object",
            extra={"request_id": rid, "model": model_id, "task": task},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned JSON that is not an object",
                rid,
            ),
        )
    return cast(dict[str, Any], loaded)


def _validate_schema(
    parsed: dict[str, Any],
    *,
    rid: str | None,
    model_id: str,
    task: CodingTask,
) -> CodingReviewResponseBody:
    try:
        return CodingReviewResponseBody.model_validate(parsed)
    except ValidationError as exc:
        log.warning(
            "coding_model_schema_mismatch",
            extra={
                "request_id": rid,
                "model": model_id,
                "task": task,
                "validation_errors": len(exc.errors()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime JSON did not match the coding review schema",
                rid,
            ),
        ) from None


# ---------------------------------------------------------------------------
# System prompts — one per task, shared user prompt builder
# ---------------------------------------------------------------------------


_JSON_SHAPE_INSTRUCTIONS = (
    "Respond with ONLY a single JSON object (no markdown fences, no "
    "commentary) with exactly these keys: "
    '"summary" (string), "findings" (array of {severity, path, line, title, '
    'explanation, recommendation}), "architecture_notes" (array of strings), '
    '"tests_to_add" (array of strings), "final_recommendation" (one of: '
    "approve, request_changes, needs_human_review). "
    "Severity MUST be one of: critical, high, medium, low, nit. "
    "Set path to one of the supplied files[].path values when the finding is "
    "file-scoped, or null when it is cross-cutting. When path is set, line "
    "MUST be the 1-indexed line number in that file, or null. "
    'When any finding has severity="critical", final_recommendation MUST NOT '
    'be "approve".'
)


def _system_prompt(task: CodingTask) -> str:
    if task == "review":
        focus = (
            "Perform a deep code review. Call out correctness bugs, race "
            "conditions, error handling gaps, missing tests, and API design "
            "issues. Separate nits from real problems using severity."
        )
    elif task == "debug":
        focus = (
            "Perform a debug-oriented review. Identify likely root causes for "
            "the behavior described in instructions, propose minimally "
            "invasive fixes, and flag places that need more evidence. Treat "
            "reproducible failures as critical or high."
        )
    elif task == "architecture":
        focus = (
            "Perform an architecture review. Focus on module boundaries, "
            "coupling, data ownership, failure modes, and scalability. Use "
            "architecture_notes liberally; findings should concentrate on "
            "specific violations of the design you recommend."
        )
    elif task == "refactor-plan":
        focus = (
            "Produce a refactor plan. Summarize the current state, list "
            "discrete refactor steps in tests_to_add / architecture_notes, "
            "and use findings only for the risks each step introduces."
        )
    else:  # security-review
        focus = (
            "Perform a security review. Prioritize authentication, "
            "authorization, injection, deserialization, secrets handling, "
            "path traversal, SSRF, and supply-chain risk. Unverified "
            'security concerns should be severity="high" or "critical" — '
            "not nit."
        )
    return (
        f"You are Sparky's premium coding intelligence engine. {focus} {_JSON_SHAPE_INSTRUCTIONS}"
    )


def _user_payload(body: CodingReviewRequestBody) -> str:
    payload: dict[str, Any] = {
        "task": body.task,
        "repository": body.repository,
        "language": body.language,
        "files": [f.model_dump() for f in body.files],
        "diff": body.diff,
        "instructions": body.instructions,
    }
    return (
        "Review the following. Return JSON only as specified in your system "
        "message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# Gateway-enforced integrity checks
# ---------------------------------------------------------------------------


def _finalize_coding_response(
    body: CodingReviewRequestBody,
    out: CodingReviewResponseBody,
    *,
    rid: str | None,
    model_id: str,
    task: CodingTask,
) -> CodingReviewResponseBody:
    """Reject inconsistent / fabricated review output."""
    # Invariant 1: never approve with a critical finding open (PLAN §15).
    if out.final_recommendation == "approve" and any(
        f.severity == "critical" for f in out.findings
    ):
        log.warning(
            "coding_approve_with_critical_finding",
            extra={
                "request_id": rid,
                "model": model_id,
                "task": task,
                "findings_count": len(out.findings),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                'text runtime recommended "approve" while also reporting a '
                'finding with severity="critical"',
                rid,
            ),
        )

    # Invariants 2 & 3: file-scoped findings must reference supplied files
    # and line numbers inside those files. Skipped when the caller did not
    # supply any files — diff-only reviews legitimately cannot be path-checked.
    if body.files:
        known_paths = {f.path: f.content for f in body.files}
        for i, finding in enumerate(out.findings):
            if finding.path is None:
                continue
            if finding.path not in known_paths:
                log.warning(
                    "coding_finding_unknown_path",
                    extra={
                        "request_id": rid,
                        "model": model_id,
                        "task": task,
                        "finding_index": i,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=envelope(
                        "runtime_error",
                        "text runtime emitted a finding whose path is not in the supplied files",
                        rid,
                    ),
                )
            if finding.line is not None:
                # Count lines as splitlines() would; the trailing newline does
                # not introduce an extra addressable line.
                line_count = len(known_paths[finding.path].splitlines()) or 1
                if finding.line > line_count:
                    log.warning(
                        "coding_finding_line_out_of_range",
                        extra={
                            "request_id": rid,
                            "model": model_id,
                            "task": task,
                            "finding_index": i,
                            "line": finding.line,
                            "line_count": line_count,
                        },
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=envelope(
                            "runtime_error",
                            "text runtime emitted a finding line outside the "
                            "supplied file's line count",
                            rid,
                        ),
                    )
    return out


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _handle_coding(
    request: Request,
    body: CodingReviewRequestBody,
    allowed_tasks: frozenset[CodingTask],
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    _require_task(body, allowed_tasks, rid)

    model_id = settings.sparky_coding_model_id
    max_tokens_cap = settings.sparky_coding_max_tokens
    requested = body.max_tokens
    effective_max_tokens = max_tokens_cap if requested is None else min(requested, max_tokens_cap)

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_system_prompt(body.task),
        user_content=_user_payload(body),
        max_tokens=effective_max_tokens,
        temperature=settings.sparky_coding_temperature,
        rid=rid,
        task=body.task,
    )
    parsed = _parse_model_json(completion, rid, model_id, body.task)
    out = _validate_schema(parsed, rid=rid, model_id=model_id, task=body.task)
    final = _finalize_coding_response(body, out, rid=rid, model_id=model_id, task=body.task)
    return JSONResponse(status_code=200, content=final.model_dump(exclude_none=True))


@router.post("/v1/coding/review", dependencies=[Depends(verify_api_key)])
async def coding_review(
    request: Request,
    body: CodingReviewRequestBody,
) -> JSONResponse:
    """Deep code review / debug review (PLAN §15)."""
    return await _handle_coding(request, body, _REVIEW_TASKS)


@router.post("/v1/coding/architecture", dependencies=[Depends(verify_api_key)])
async def coding_architecture(
    request: Request,
    body: CodingReviewRequestBody,
) -> JSONResponse:
    """Architecture review (PLAN §15)."""
    return await _handle_coding(request, body, _ARCHITECTURE_TASKS)


@router.post("/v1/coding/refactor-plan", dependencies=[Depends(verify_api_key)])
async def coding_refactor_plan(
    request: Request,
    body: CodingReviewRequestBody,
) -> JSONResponse:
    """Refactor plan (PLAN §15)."""
    return await _handle_coding(request, body, _REFACTOR_TASKS)


@router.post("/v1/coding/security-review", dependencies=[Depends(verify_api_key)])
async def coding_security_review(
    request: Request,
    body: CodingReviewRequestBody,
) -> JSONResponse:
    """Security review (PLAN §15)."""
    return await _handle_coding(request, body, _SECURITY_TASKS)
