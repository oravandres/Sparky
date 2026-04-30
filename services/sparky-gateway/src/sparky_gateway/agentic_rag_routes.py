"""POST /v1/agentic-rag/* — Sparky's agentic RAG brain (PLAN §5.3, §6, §14).

Sparky owns the intelligence stages of the agentic RAG loop:
planning, evidence evaluation, synthesis, verification, and finalization.
MiMi still owns Qdrant, Postgres, ingestion, and the retrieval tool calls
themselves (PLAN §6.1).

Each handler:
  1. Validates the caller payload (Pydantic, ``extra='forbid'``).
  2. Builds a constrained prompt that instructs Nemotron to emit ONLY a
     single JSON object matching the PLAN §6 schema for that stage.
  3. Proxies to the configured text runtime via the already-throttled
     Nemotron semaphore and HTTP client.
  4. Parses and validates the model output against a strict Pydantic
     response schema; any schema drift returns HTTP 502.
  5. Applies integrity checks that the model cannot be trusted with
     (e.g. citations must reference a supplied chunk; rounds must not
     exceed the caller's ``max_retrieval_rounds``).

The goal is that source IDs and chunk IDs survive the full flow and that
the gateway — not the model — is the authority on "this claim cites a
chunk that was actually in the evidence pack".
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .auth import verify_api_key
from .chat_routes import _require_approved_text_model, _text_runtime_base_url
from .config import Settings
from .errors import envelope
from .registry import Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["agentic-rag"])


# ---------------------------------------------------------------------------
# Shared request/response bounds
# ---------------------------------------------------------------------------

_MAX_QUESTION_CHARS = 48_000
_MAX_DRAFT_CHARS = 120_000
_MAX_ANSWER_CHARS = 120_000
_MAX_CHUNK_TEXT = 32_000
_MAX_CHUNK_TITLE = 1_024
_MAX_EVIDENCE_CHUNKS = 128
_MAX_SOURCES = 64
_MAX_REQUIRED_FACTS = 64
_MAX_FACT_CHARS = 2_048
_MAX_TOOLS = 4
_MAX_ROUND_QUERIES = 16
_MAX_ROUNDS_HARD = 10
_MAX_TOP_K = 200


class EvidenceChunk(BaseModel):
    """One retrieved chunk (PLAN §6.5)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    chunk_id: str = Field(min_length=1, max_length=256)
    source_id: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=_MAX_CHUNK_TITLE)
    text: str = Field(min_length=1, max_length=_MAX_CHUNK_TEXT)
    metadata: dict[str, Any] | None = None


def _chunk_index(chunks: list[EvidenceChunk]) -> set[tuple[str, str]]:
    """Pair set for fast `(source_id, chunk_id)` citation checks."""
    return {(c.source_id, c.chunk_id) for c in chunks}


# ---------------------------------------------------------------------------
# /v1/agentic-rag/plan  (PLAN §6.3 / §6.4)
# ---------------------------------------------------------------------------


class AvailableSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    source_id: str = Field(min_length=1, max_length=256)
    source_type: Literal["docs", "code", "pdf", "audio", "video", "web", "database"]
    description: str | None = Field(default=None, max_length=8_000)
    metadata: dict[str, Any] | None = None


class PlanConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    require_citations: bool = True
    max_retrieval_rounds: int = Field(default=3, ge=1, le=_MAX_ROUNDS_HARD)
    answer_style: Literal["technical", "executive", "concise", "detailed"] | None = None


class RagPlanRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    user_intent: (
        Literal["unknown", "question", "analysis", "coding", "research", "summary"] | None
    ) = None
    available_sources: list[AvailableSource] = Field(default_factory=list, max_length=_MAX_SOURCES)
    constraints: PlanConstraints | None = None


class RetrievalRoundOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round: int = Field(ge=1, le=_MAX_ROUNDS_HARD)
    queries: list[str] = Field(min_length=1, max_length=_MAX_ROUND_QUERIES)
    tools: list[Literal["vector_search", "keyword_search", "metadata_search", "code_search"]] = (
        Field(min_length=1, max_length=_MAX_TOOLS)
    )
    filters: dict[str, Any] | None = None
    top_k: int = Field(default=30, ge=1, le=_MAX_TOP_K)
    minimum_evidence: str | None = None


class RagPlanResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=2_048)
    needs_rag: bool
    required_facts: list[str] = Field(default_factory=list, max_length=_MAX_REQUIRED_FACTS)
    retrieval_rounds: list[RetrievalRoundOut] = Field(default_factory=list)
    reasoning_notes: str | None = Field(default=None, max_length=8_000)

    @field_validator("required_facts")
    @classmethod
    def _fact_items(cls, v: list[str]) -> list[str]:
        for i, s in enumerate(v):
            if len(s) > _MAX_FACT_CHARS:
                raise ValueError(f"required_facts[{i}] exceeds {_MAX_FACT_CHARS} characters")
        return v


# ---------------------------------------------------------------------------
# /v1/agentic-rag/evaluate-evidence  (PLAN §6.5 / §6.6)
# ---------------------------------------------------------------------------


class RagEvaluateRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    evidence_chunks: list[EvidenceChunk] = Field(
        default_factory=list, max_length=_MAX_EVIDENCE_CHUNKS
    )
    required_facts: list[str] = Field(default_factory=list, max_length=_MAX_REQUIRED_FACTS)


class ContradictionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=4_096)
    chunk_ids: list[str] = Field(default_factory=list, max_length=_MAX_EVIDENCE_CHUNKS)


class RagEvaluateResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sufficient: bool
    missing_facts: list[str] = Field(default_factory=list, max_length=_MAX_REQUIRED_FACTS)
    contradictions: list[ContradictionOut] = Field(default_factory=list)
    recommended_followup_queries: list[str] = Field(
        default_factory=list, max_length=_MAX_ROUND_QUERIES
    )
    confidence: Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# /v1/agentic-rag/synthesize  (PLAN §6.7 / §6.8)
# ---------------------------------------------------------------------------


class RagSynthesizeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    evidence_chunks: list[EvidenceChunk] = Field(min_length=1, max_length=_MAX_EVIDENCE_CHUNKS)
    answer_style: Literal["technical", "executive", "concise", "detailed"] | None = None
    require_citations: bool = True
    max_tokens: int = Field(default=4096, ge=256, le=16384)


class CitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=256)
    chunk_id: str = Field(min_length=1, max_length=256)
    claim: str = Field(min_length=1, max_length=4_096)


class RagSynthesizeResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=_MAX_ANSWER_CHARS)
    citations: list[CitationOut] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    needs_more_retrieval: bool


# ---------------------------------------------------------------------------
# /v1/agentic-rag/verify  (PLAN §6.9 / §6.10)
# ---------------------------------------------------------------------------


class RagVerifyRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    answer: str = Field(min_length=1, max_length=_MAX_ANSWER_CHARS)
    evidence_chunks: list[EvidenceChunk] = Field(min_length=1, max_length=_MAX_EVIDENCE_CHUNKS)


class RagVerifyResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    final_answer_ready: bool


# ---------------------------------------------------------------------------
# /v1/agentic-rag/finalize  (PLAN §6.11)
# ---------------------------------------------------------------------------


class FinalizeVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supported_claims: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class RagFinalizeRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    question: str = Field(min_length=1, max_length=_MAX_QUESTION_CHARS)
    draft_answer: str = Field(min_length=1, max_length=_MAX_DRAFT_CHARS)
    evidence_chunks: list[EvidenceChunk] = Field(min_length=1, max_length=_MAX_EVIDENCE_CHUNKS)
    verification: FinalizeVerification | None = None
    format: Literal["markdown", "plaintext", "json"] | None = None
    citation_style: Literal["inline", "footnote", "none"] | None = None
    answer_style: Literal["technical", "executive", "concise", "detailed"] | None = None


class FinalCitationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marker: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=256)
    chunk_id: str = Field(min_length=1, max_length=256)
    claim: str = Field(min_length=1, max_length=4_096)


class RagFinalizeResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_answer: str = Field(min_length=1, max_length=_MAX_ANSWER_CHARS)
    citations: list[FinalCitationOut] = Field(default_factory=list)
    removed_unsupported_claims: list[str] = Field(default_factory=list)
    flagged_contradictions: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    ready_for_user: bool


# ---------------------------------------------------------------------------
# Nemotron upstream helpers (mirror reasoning_routes; kept private to this
# module so the agentic-rag PR does not churn the reasoning module)
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
    stage: str,
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
                "agentic_rag_upstream_unreachable",
                extra={
                    "request_id": rid,
                    "stage": stage,
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
                "agentic_rag_upstream_cancelled",
                extra={"request_id": rid, "stage": stage},
            )
            raise

    if upstream.status_code < 200 or upstream.status_code >= 300:
        log.warning(
            "agentic_rag_upstream_error",
            extra={
                "request_id": rid,
                "stage": stage,
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
    completion: dict[str, Any], rid: str | None, model_id: str, stage: str
) -> dict[str, Any]:
    raw = _openai_choice_text(completion)
    if raw is None:
        log.warning(
            "agentic_rag_model_empty_content",
            extra={"request_id": rid, "model": model_id, "stage": stage},
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
            "agentic_rag_model_invalid_json",
            extra={"request_id": rid, "model": model_id, "stage": stage},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime did not return valid JSON for agentic-rag output",
                rid,
            ),
        ) from None
    if not isinstance(loaded, dict):
        log.warning(
            "agentic_rag_model_json_not_object",
            extra={"request_id": rid, "model": model_id, "stage": stage},
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
    out_cls: type[BaseModel],
    parsed: dict[str, Any],
    *,
    rid: str | None,
    model_id: str,
    stage: str,
) -> BaseModel:
    try:
        return out_cls.model_validate(parsed)
    except ValidationError as exc:
        log.warning(
            "agentic_rag_model_schema_mismatch",
            extra={
                "request_id": rid,
                "model": model_id,
                "stage": stage,
                "validation_errors": len(exc.errors()),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime JSON did not match the agentic-rag schema",
                rid,
            ),
        ) from None


# ---------------------------------------------------------------------------
# Prompt templates — strict JSON contract on every stage
# ---------------------------------------------------------------------------


def _plan_system_prompt() -> str:
    return (
        "You are Sparky's agentic RAG planner. Decide whether retrieval is "
        "needed, decompose the question into concrete queries, and select "
        "retrieval tools. Respond with ONLY a single JSON object (no markdown "
        "fences, no commentary) with exactly these keys: "
        '"intent" (string), "needs_rag" (bool), "required_facts" (array of '
        'strings), "retrieval_rounds" (array of {round:int, queries:array of '
        "strings, tools:array (subset of vector_search, keyword_search, "
        "metadata_search, code_search), filters:object, top_k:int, "
        'minimum_evidence:string}), "reasoning_notes" (string). '
        "Round numbers start at 1 and increase; never exceed "
        "constraints.max_retrieval_rounds. If needs_rag is false, "
        "retrieval_rounds must be []."
    )


def _plan_user_payload(body: RagPlanRequestBody) -> str:
    payload = {
        "question": body.question,
        "user_intent": body.user_intent or "unknown",
        "available_sources": [s.model_dump(exclude_none=True) for s in body.available_sources],
        "constraints": (
            body.constraints.model_dump(exclude_none=True)
            if body.constraints is not None
            else {"require_citations": True, "max_retrieval_rounds": 3}
        ),
    }
    return (
        "Produce a retrieval plan. Return JSON only as specified in your "
        "system message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _evaluate_system_prompt() -> str:
    return (
        "You are Sparky's evidence auditor. Decide whether the supplied "
        "evidence is sufficient to answer the question. Respond with ONLY a "
        "single JSON object (no markdown fences, no commentary) with keys: "
        '"sufficient" (bool), "missing_facts" (array of strings), '
        '"contradictions" (array of {summary:string, chunk_ids:array of '
        "strings referencing supplied chunk_ids}), "
        '"recommended_followup_queries" (array of strings), "confidence" '
        "(high|medium|low). Every chunk_id referenced under contradictions "
        "MUST appear in the supplied evidence_chunks; do not invent ids. "
        'Prefer "insufficient" plus follow-up queries over guessing.'
    )


def _evaluate_user_payload(body: RagEvaluateRequestBody) -> str:
    payload = {
        "question": body.question,
        "required_facts": body.required_facts,
        "evidence_chunks": [c.model_dump(exclude_none=True) for c in body.evidence_chunks],
    }
    return (
        "Audit the evidence. Return JSON only as specified in your system "
        "message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _synthesize_system_prompt(require_citations: bool) -> str:
    citation_rule = (
        "Every substantive sentence in the answer MUST be supported by at "
        "least one citation whose source_id/chunk_id pair appears in the "
        "supplied evidence_chunks. Do not invent ids."
        if require_citations
        else "Prefer citations that reference supplied evidence_chunks; if an "
        "id is invented it will be rejected."
    )
    return (
        "You are Sparky's premium synthesis engine. Produce a citation-aware "
        "answer from the supplied evidence. Respond with ONLY a single JSON "
        "object (no markdown fences, no commentary) with keys: "
        '"answer" (string), "citations" (array of {source_id, chunk_id, '
        'claim}), "unsupported_claims" (array of strings — statements the '
        "evidence does not support, surfaced separately rather than hidden "
        'in the answer), "confidence" (high|medium|low), '
        '"needs_more_retrieval" (bool). '
        f"{citation_rule}"
    )


def _synthesize_user_payload(body: RagSynthesizeRequestBody) -> str:
    payload = {
        "question": body.question,
        "answer_style": body.answer_style or "technical",
        "require_citations": body.require_citations,
        "evidence_chunks": [c.model_dump(exclude_none=True) for c in body.evidence_chunks],
    }
    return (
        "Synthesize the answer. Return JSON only as specified in your system "
        "message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _verify_system_prompt() -> str:
    return (
        "You are Sparky's answer verifier. Inspect the candidate answer and "
        "classify each distinct claim against the supplied evidence. Respond "
        "with ONLY a single JSON object (no markdown fences, no commentary) "
        'with keys: "supported_claims" (array of strings), '
        '"unsupported_claims" (array of strings), "contradictions" (array '
        'of strings), "confidence" (high|medium|low), "final_answer_ready" '
        '(bool). Set "final_answer_ready" to false whenever any claim is '
        "unsupported or contradicted. Do not invent new claims; only "
        "classify those already present in the answer."
    )


def _verify_user_payload(body: RagVerifyRequestBody) -> str:
    payload = {
        "answer": body.answer,
        "evidence_chunks": [c.model_dump(exclude_none=True) for c in body.evidence_chunks],
    }
    return (
        "Verify the answer. Return JSON only as specified in your system "
        "message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def _finalize_system_prompt(citation_style: str, fmt: str) -> str:
    return (
        "You are Sparky's final-answer editor. Take the verified draft and "
        "produce the user-facing response. Respond with ONLY a single JSON "
        "object (no markdown fences, no commentary) with keys: "
        '"final_answer" (string formatted per requested format), '
        '"citations" (array of {marker, source_id, chunk_id, claim}), '
        '"removed_unsupported_claims" (array of strings — claims dropped '
        "because the verification said they were unsupported), "
        '"flagged_contradictions" (array of strings — contradictions called '
        'out inline), "confidence" (high|medium|low), "ready_for_user" '
        f'(bool). Use citation_style="{citation_style}" and '
        f'format="{fmt}". Every citation marker in the final_answer (if '
        "citation_style is inline or footnote) must match one of the "
        "citations[].marker values, and every citation.source_id/chunk_id "
        "pair must reference the supplied evidence_chunks."
    )


def _finalize_user_payload(body: RagFinalizeRequestBody) -> str:
    payload = {
        "question": body.question,
        "draft_answer": body.draft_answer,
        "verification": (
            body.verification.model_dump(exclude_none=True)
            if body.verification is not None
            else {"supported_claims": [], "unsupported_claims": [], "contradictions": []}
        ),
        "format": body.format or "markdown",
        "citation_style": body.citation_style or "inline",
        "answer_style": body.answer_style or "technical",
        "evidence_chunks": [c.model_dump(exclude_none=True) for c in body.evidence_chunks],
    }
    return (
        "Produce the final answer. Return JSON only as specified in your "
        "system message.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# Gateway-enforced post-response integrity checks
# ---------------------------------------------------------------------------


def _finalize_plan_response(
    body: RagPlanRequestBody,
    out: RagPlanResponseBody,
    *,
    rid: str | None,
    model_id: str,
) -> RagPlanResponseBody:
    """Bound the model's plan to the caller's constraints."""
    max_rounds = body.constraints.max_retrieval_rounds if body.constraints else 3

    if not out.needs_rag and out.retrieval_rounds:
        log.warning(
            "agentic_rag_plan_rounds_without_need",
            extra={"request_id": rid, "model": model_id, "rounds": len(out.retrieval_rounds)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime returned retrieval_rounds but needs_rag=false",
                rid,
            ),
        )

    if len(out.retrieval_rounds) > max_rounds:
        log.warning(
            "agentic_rag_plan_rounds_over_cap",
            extra={
                "request_id": rid,
                "model": model_id,
                "rounds": len(out.retrieval_rounds),
                "max_rounds": max_rounds,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime exceeded the caller's max_retrieval_rounds",
                rid,
            ),
        )

    seen_rounds: set[int] = set()
    for r in out.retrieval_rounds:
        if r.round in seen_rounds:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=envelope(
                    "runtime_error",
                    "text runtime emitted duplicate round numbers",
                    rid,
                ),
            )
        seen_rounds.add(r.round)

    return out


def _finalize_evaluate_response(
    body: RagEvaluateRequestBody,
    out: RagEvaluateResponseBody,
    *,
    rid: str | None,
    model_id: str,
) -> RagEvaluateResponseBody:
    """Reject invented chunk ids in contradictions."""
    supplied_chunk_ids = {c.chunk_id for c in body.evidence_chunks}
    for con in out.contradictions:
        unknown = [cid for cid in con.chunk_ids if cid not in supplied_chunk_ids]
        if unknown:
            log.warning(
                "agentic_rag_evaluate_unknown_chunk_ids",
                extra={
                    "request_id": rid,
                    "model": model_id,
                    "unknown_chunk_ids": len(unknown),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=envelope(
                    "runtime_error",
                    "text runtime referenced chunk_ids outside the supplied evidence",
                    rid,
                ),
            )
    return out


def _finalize_synthesize_response(
    body: RagSynthesizeRequestBody,
    out: RagSynthesizeResponseBody,
    *,
    rid: str | None,
    model_id: str,
) -> RagSynthesizeResponseBody:
    """Every citation must reference a supplied (source_id, chunk_id) pair."""
    supplied = _chunk_index(body.evidence_chunks)
    bad = [c for c in out.citations if (c.source_id, c.chunk_id) not in supplied]
    if bad:
        log.warning(
            "agentic_rag_synthesize_invented_citation",
            extra={
                "request_id": rid,
                "model": model_id,
                "invented_citations": len(bad),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime emitted citations outside the supplied evidence",
                rid,
            ),
        )
    return out


def _finalize_finalize_response(
    body: RagFinalizeRequestBody,
    out: RagFinalizeResponseBody,
    *,
    rid: str | None,
    model_id: str,
) -> RagFinalizeResponseBody:
    """Final citations must reference supplied evidence; markers must be unique."""
    supplied = _chunk_index(body.evidence_chunks)
    bad = [c for c in out.citations if (c.source_id, c.chunk_id) not in supplied]
    if bad:
        log.warning(
            "agentic_rag_finalize_invented_citation",
            extra={
                "request_id": rid,
                "model": model_id,
                "invented_citations": len(bad),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime emitted final citations outside the supplied evidence",
                rid,
            ),
        )
    markers = [c.marker for c in out.citations]
    if len(markers) != len(set(markers)):
        log.warning(
            "agentic_rag_finalize_duplicate_marker",
            extra={"request_id": rid, "model": model_id},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=envelope(
                "runtime_error",
                "text runtime reused citation markers in the final answer",
                rid,
            ),
        )
    return out


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/v1/agentic-rag/plan", dependencies=[Depends(verify_api_key)])
async def agentic_rag_plan(
    request: Request,
    body: RagPlanRequestBody,
) -> JSONResponse:
    """Produce a multi-round retrieval plan (PLAN §6.3 / §6.4)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_agentic_rag_model_id

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_plan_system_prompt(),
        user_content=_plan_user_payload(body),
        max_tokens=settings.sparky_agentic_rag_plan_max_tokens,
        temperature=settings.sparky_agentic_rag_temperature,
        rid=rid,
        stage="plan",
    )
    parsed = _parse_model_json(completion, rid, model_id, stage="plan")
    out = cast(
        RagPlanResponseBody,
        _validate_schema(RagPlanResponseBody, parsed, rid=rid, model_id=model_id, stage="plan"),
    )
    final = _finalize_plan_response(body, out, rid=rid, model_id=model_id)
    return JSONResponse(status_code=200, content=final.model_dump(exclude_none=True))


@router.post("/v1/agentic-rag/evaluate-evidence", dependencies=[Depends(verify_api_key)])
async def agentic_rag_evaluate(
    request: Request,
    body: RagEvaluateRequestBody,
) -> JSONResponse:
    """Decide whether retrieved evidence is enough (PLAN §6.5 / §6.6)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_agentic_rag_model_id

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_evaluate_system_prompt(),
        user_content=_evaluate_user_payload(body),
        max_tokens=settings.sparky_agentic_rag_evaluate_max_tokens,
        temperature=settings.sparky_agentic_rag_temperature,
        rid=rid,
        stage="evaluate",
    )
    parsed = _parse_model_json(completion, rid, model_id, stage="evaluate")
    out = cast(
        RagEvaluateResponseBody,
        _validate_schema(
            RagEvaluateResponseBody, parsed, rid=rid, model_id=model_id, stage="evaluate"
        ),
    )
    final = _finalize_evaluate_response(body, out, rid=rid, model_id=model_id)
    return JSONResponse(status_code=200, content=final.model_dump(exclude_none=True))


@router.post("/v1/agentic-rag/synthesize", dependencies=[Depends(verify_api_key)])
async def agentic_rag_synthesize(
    request: Request,
    body: RagSynthesizeRequestBody,
) -> JSONResponse:
    """Draft a citation-aware answer (PLAN §6.7 / §6.8)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_agentic_rag_model_id
    mt = min(body.max_tokens, settings.sparky_agentic_rag_synthesize_max_tokens)

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_synthesize_system_prompt(body.require_citations),
        user_content=_synthesize_user_payload(body),
        max_tokens=mt,
        temperature=settings.sparky_agentic_rag_temperature,
        rid=rid,
        stage="synthesize",
    )
    parsed = _parse_model_json(completion, rid, model_id, stage="synthesize")
    out = cast(
        RagSynthesizeResponseBody,
        _validate_schema(
            RagSynthesizeResponseBody,
            parsed,
            rid=rid,
            model_id=model_id,
            stage="synthesize",
        ),
    )
    final = _finalize_synthesize_response(body, out, rid=rid, model_id=model_id)
    return JSONResponse(status_code=200, content=final.model_dump(exclude_none=True))


@router.post("/v1/agentic-rag/verify", dependencies=[Depends(verify_api_key)])
async def agentic_rag_verify(
    request: Request,
    body: RagVerifyRequestBody,
) -> JSONResponse:
    """Classify answer claims against the supplied evidence (PLAN §6.9 / §6.10)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_agentic_rag_model_id

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_verify_system_prompt(),
        user_content=_verify_user_payload(body),
        max_tokens=settings.sparky_agentic_rag_verify_max_tokens,
        temperature=settings.sparky_agentic_rag_temperature,
        rid=rid,
        stage="verify",
    )
    parsed = _parse_model_json(completion, rid, model_id, stage="verify")
    out = cast(
        RagVerifyResponseBody,
        _validate_schema(RagVerifyResponseBody, parsed, rid=rid, model_id=model_id, stage="verify"),
    )
    return JSONResponse(status_code=200, content=out.model_dump(exclude_none=True))


@router.post("/v1/agentic-rag/finalize", dependencies=[Depends(verify_api_key)])
async def agentic_rag_finalize(
    request: Request,
    body: RagFinalizeRequestBody,
) -> JSONResponse:
    """Produce the user-facing final answer (PLAN §6.11)."""
    settings: Settings = request.app.state.settings
    rid = getattr(request.state, "request_id", None)
    model_id = settings.sparky_agentic_rag_model_id

    completion = await _post_upstream_chat(
        request,
        model_id=model_id,
        system_prompt=_finalize_system_prompt(
            citation_style=body.citation_style or "inline",
            fmt=body.format or "markdown",
        ),
        user_content=_finalize_user_payload(body),
        max_tokens=settings.sparky_agentic_rag_finalize_max_tokens,
        temperature=settings.sparky_agentic_rag_temperature,
        rid=rid,
        stage="finalize",
    )
    parsed = _parse_model_json(completion, rid, model_id, stage="finalize")
    out = cast(
        RagFinalizeResponseBody,
        _validate_schema(
            RagFinalizeResponseBody, parsed, rid=rid, model_id=model_id, stage="finalize"
        ),
    )
    final = _finalize_finalize_response(body, out, rid=rid, model_id=model_id)
    return JSONResponse(status_code=200, content=final.model_dump(exclude_none=True))
