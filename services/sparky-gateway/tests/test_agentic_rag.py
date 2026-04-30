"""POST /v1/agentic-rag/* — structured Nemotron-backed RAG brain (PLAN §6, §14)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sparky_gateway.agentic_rag_routes import (
    EvidenceChunk,
    RagEvaluateRequestBody,
    RagEvaluateResponseBody,
    RagFinalizeRequestBody,
    RagFinalizeResponseBody,
    RagPlanRequestBody,
    RagPlanResponseBody,
    RagSynthesizeRequestBody,
    RagSynthesizeResponseBody,
    RagVerifyResponseBody,
    _finalize_evaluate_response,
    _finalize_finalize_response,
    _finalize_plan_response,
    _finalize_synthesize_response,
    _finalize_verify_response,
)
from sparky_gateway.config import Settings
from sparky_gateway.main import create_app

_PLAN_OK: dict[str, Any] = {
    "intent": "question",
    "needs_rag": True,
    "required_facts": ["fact A"],
    "retrieval_rounds": [
        {
            "round": 1,
            "queries": ["what is A?"],
            "tools": ["vector_search"],
            "filters": {},
            "top_k": 20,
            "minimum_evidence": "1 chunk",
        }
    ],
    "reasoning_notes": "initial pass",
}

_EVIDENCE = [
    {"chunk_id": "c1", "source_id": "s1", "text": "Alpha is the first letter.", "title": "A"},
    {"chunk_id": "c2", "source_id": "s2", "text": "Beta is the second letter.", "title": "B"},
]

_EVAL_OK: dict[str, Any] = {
    "sufficient": True,
    "missing_facts": [],
    "contradictions": [],
    "recommended_followup_queries": [],
    "confidence": "high",
}

_SYNTH_OK: dict[str, Any] = {
    "answer": "Alpha is first; beta is second.",
    "citations": [
        {"source_id": "s1", "chunk_id": "c1", "claim": "Alpha is first."},
        {"source_id": "s2", "chunk_id": "c2", "claim": "Beta is second."},
    ],
    "unsupported_claims": [],
    "confidence": "high",
    "needs_more_retrieval": False,
}

_VERIFY_OK: dict[str, Any] = {
    "supported_claims": ["Alpha is first."],
    "unsupported_claims": [],
    "contradictions": [],
    "confidence": "high",
    "final_answer_ready": True,
}

_FINALIZE_OK: dict[str, Any] = {
    "final_answer": "Alpha is first [1]; beta is second [2].",
    "citations": [
        {"marker": "1", "source_id": "s1", "chunk_id": "c1", "claim": "Alpha is first."},
        {"marker": "2", "source_id": "s2", "chunk_id": "c2", "claim": "Beta is second."},
    ],
    "removed_unsupported_claims": [],
    "flagged_contradictions": [],
    "confidence": "high",
    "ready_for_user": True,
}


def _mock_upstream(content: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(content)}}]}
    return resp


# ---------------------------------------------------------------------------
# Auth + schema gates (5 routes)
# ---------------------------------------------------------------------------


def test_plan_requires_auth(client: TestClient) -> None:
    r = client.post("/v1/agentic-rag/plan", json={"question": "q?"})
    assert r.status_code == 401


def test_evaluate_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/agentic-rag/evaluate-evidence",
        json={"question": "q?", "evidence_chunks": []},
    )
    assert r.status_code == 401


def test_synthesize_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/agentic-rag/synthesize",
        json={"question": "q?", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 401


def test_verify_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/agentic-rag/verify",
        json={"answer": "a", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 401


def test_finalize_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/agentic-rag/finalize",
        json={"question": "q?", "draft_answer": "a", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 401


def test_plan_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?", "unexpected": True},
    )
    assert r.status_code == 422


def test_synthesize_requires_evidence_chunks(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/agentic-rag/synthesize",
        headers=auth_header,
        json={"question": "q?", "evidence_chunks": []},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Happy paths — the gateway proxies, validates JSON, returns strict output
# ---------------------------------------------------------------------------


def test_plan_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_PLAN_OK))
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={
            "question": "How does X work?",
            "user_intent": "question",
            "constraints": {"max_retrieval_rounds": 2},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["needs_rag"] is True
    assert body["retrieval_rounds"][0]["round"] == 1
    assert body["retrieval_rounds"][0]["tools"] == ["vector_search"]


def test_evaluate_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_EVAL_OK))
    r = client.post(
        "/v1/agentic-rag/evaluate-evidence",
        headers=auth_header,
        json={"question": "q?", "evidence_chunks": _EVIDENCE, "required_facts": ["f"]},
    )
    assert r.status_code == 200
    assert r.json()["sufficient"] is True


def test_synthesize_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_SYNTH_OK))
    r = client.post(
        "/v1/agentic-rag/synthesize",
        headers=auth_header,
        json={"question": "What are A and B?", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == "high"
    assert len(body["citations"]) == 2


def test_verify_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_VERIFY_OK))
    r = client.post(
        "/v1/agentic-rag/verify",
        headers=auth_header,
        json={"answer": "Alpha is first.", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 200
    assert r.json()["final_answer_ready"] is True


def test_finalize_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_FINALIZE_OK))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "Alpha and beta.",
            "evidence_chunks": _EVIDENCE,
            "format": "markdown",
            "citation_style": "inline",
        },
    )
    assert r.status_code == 200
    assert r.json()["ready_for_user"] is True


# ---------------------------------------------------------------------------
# Model-side failure modes — gateway returns 502
# ---------------------------------------------------------------------------


def test_plan_502_on_invalid_json(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = {"choices": [{"message": {"content": "not json at all"}}]}
    client.app.state.http_client.post = AsyncMock(return_value=resp)
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "runtime_error"


def test_synthesize_502_when_citations_are_invented(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_SYNTH_OK)
    bad["citations"] = [
        {"source_id": "ghost", "chunk_id": "unknown", "claim": "Fabricated."},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/synthesize",
        headers=auth_header,
        json={"question": "q?", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "runtime_error"


def test_evaluate_502_when_contradiction_chunk_id_unknown(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_EVAL_OK)
    bad["contradictions"] = [{"summary": "x", "chunk_ids": ["ghost"]}]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/evaluate-evidence",
        headers=auth_header,
        json={"question": "q?", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 502


def test_plan_502_when_rounds_exceed_caller_cap(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_PLAN_OK)
    bad["retrieval_rounds"] = [
        {"round": 1, "queries": ["q"], "tools": ["vector_search"]},
        {"round": 2, "queries": ["q"], "tools": ["vector_search"]},
        {"round": 3, "queries": ["q"], "tools": ["vector_search"]},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?", "constraints": {"max_retrieval_rounds": 2}},
    )
    assert r.status_code == 502


def test_plan_502_when_needs_rag_false_but_rounds_present(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_PLAN_OK)
    bad["needs_rag"] = False
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?"},
    )
    assert r.status_code == 502


def test_finalize_502_when_markers_collide(client: TestClient, auth_header: dict[str, str]) -> None:
    bad = dict(_FINALIZE_OK)
    bad["citations"] = [
        {"marker": "1", "source_id": "s1", "chunk_id": "c1", "claim": "A."},
        {"marker": "1", "source_id": "s2", "chunk_id": "c2", "claim": "B."},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "a",
            "evidence_chunks": _EVIDENCE,
        },
    )
    assert r.status_code == 502


def test_finalize_502_when_citation_invented(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_FINALIZE_OK)
    bad["citations"] = [
        {"marker": "1", "source_id": "ghost", "chunk_id": "unknown", "claim": "x"},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "a",
            "evidence_chunks": _EVIDENCE,
        },
    )
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# PR feedback regressions
# ---------------------------------------------------------------------------


def test_evaluate_rejects_omitted_evidence_chunks(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Caller bug (missing field) must 422, not silently become an empty pack."""
    r = client.post(
        "/v1/agentic-rag/evaluate-evidence",
        headers=auth_header,
        json={"question": "q?"},
    )
    assert r.status_code == 422


def test_evaluate_accepts_explicit_empty_evidence_chunks(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """An explicit empty pack is a legitimate input (e.g. "is retrieval needed?")."""
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_EVAL_OK))
    r = client.post(
        "/v1/agentic-rag/evaluate-evidence",
        headers=auth_header,
        json={"question": "q?", "evidence_chunks": []},
    )
    assert r.status_code == 200


def test_synthesize_accepts_max_tokens_below_256(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Contract (api-contract.yaml) advertises minimum=1; do not 422 on 128."""
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_SYNTH_OK))
    r = client.post(
        "/v1/agentic-rag/synthesize",
        headers=auth_header,
        json={
            "question": "q?",
            "evidence_chunks": _EVIDENCE,
            "max_tokens": 128,
        },
    )
    assert r.status_code == 200


def test_plan_502_when_single_round_value_exceeds_cap(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """A `{round: 10}` entry under max_retrieval_rounds=3 must be rejected."""
    bad = dict(_PLAN_OK)
    bad["retrieval_rounds"] = [
        {"round": 10, "queries": ["q"], "tools": ["vector_search"]},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?", "constraints": {"max_retrieval_rounds": 3}},
    )
    assert r.status_code == 502


def test_plan_502_when_rounds_have_gap(client: TestClient, auth_header: dict[str, str]) -> None:
    """Rounds must form the contiguous sequence 1..n; [1, 3] is rejected."""
    bad = dict(_PLAN_OK)
    bad["retrieval_rounds"] = [
        {"round": 1, "queries": ["q1"], "tools": ["vector_search"]},
        {"round": 3, "queries": ["q3"], "tools": ["vector_search"]},
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/plan",
        headers=auth_header,
        json={"question": "q?", "constraints": {"max_retrieval_rounds": 3}},
    )
    assert r.status_code == 502


def test_finalize_502_when_final_answer_uses_unknown_inline_marker(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """final_answer contains [9] but only [1] was declared → 502."""
    bad = dict(_FINALIZE_OK)
    bad["final_answer"] = "Alpha is first [9]; beta is second [2]."
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "d",
            "evidence_chunks": _EVIDENCE,
            "citation_style": "inline",
        },
    )
    assert r.status_code == 502


def test_finalize_502_when_final_answer_uses_unknown_footnote_marker(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_FINALIZE_OK)
    bad["citations"] = [
        {"marker": "1", "source_id": "s1", "chunk_id": "c1", "claim": "A"},
    ]
    bad["final_answer"] = "Claim [^ghost]."
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "d",
            "evidence_chunks": _EVIDENCE,
            "citation_style": "footnote",
        },
    )
    assert r.status_code == 502


def test_finalize_accepts_non_marker_brackets_when_citation_style_none(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """`citation_style=none` → no scanning, `[TODO]` in prose is allowed."""
    ok = dict(_FINALIZE_OK)
    ok["final_answer"] = "Answer with [TODO] placeholder."
    ok["citations"] = []
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "d",
            "evidence_chunks": _EVIDENCE,
            "citation_style": "none",
        },
    )
    assert r.status_code == 200


def test_finalize_inline_allows_markdown_links_and_prose_brackets(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Inline scanner is numeric-only; Markdown `[text](url)` must not 502."""
    ok = dict(_FINALIZE_OK)
    ok["final_answer"] = (
        "Alpha is first [1]; see [docs](https://example.com/a) "
        "and note [TODO] and [section 2]. Beta is second [2]."
    )
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "d",
            "evidence_chunks": _EVIDENCE,
            "citation_style": "inline",
        },
    )
    assert r.status_code == 200


def test_finalize_inline_ignores_markdown_link_whose_text_is_numeric(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """`[9](url)` is a Markdown link, not an invented inline marker."""
    ok = dict(_FINALIZE_OK)
    ok["final_answer"] = "See [9](https://example.com/nine) and [1] and [2]."
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/agentic-rag/finalize",
        headers=auth_header,
        json={
            "question": "q?",
            "draft_answer": "d",
            "evidence_chunks": _EVIDENCE,
            "citation_style": "inline",
        },
    )
    assert r.status_code == 200


def test_verify_502_when_ready_but_unsupported_claims_present(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """final_answer_ready=true must not coexist with non-empty unsupported_claims."""
    bad = dict(_VERIFY_OK)
    bad["unsupported_claims"] = ["Alpha is actually third."]
    bad["final_answer_ready"] = True
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/verify",
        headers=auth_header,
        json={"answer": "Alpha is first.", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 502


def test_verify_502_when_ready_but_contradictions_present(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_VERIFY_OK)
    bad["contradictions"] = ["c1 and c2 disagree."]
    bad["final_answer_ready"] = True
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/agentic-rag/verify",
        headers=auth_header,
        json={"answer": "a", "evidence_chunks": _EVIDENCE},
    )
    assert r.status_code == 502


def test_finalize_verify_helper_accepts_ready_when_all_supported() -> None:
    """Direct helper call — keeps the invariant even if Pydantic is bypassed."""
    out = RagVerifyResponseBody.model_validate(
        {
            "supported_claims": ["s"],
            "unsupported_claims": [],
            "contradictions": [],
            "confidence": "high",
            "final_answer_ready": True,
        }
    )
    result = _finalize_verify_response(out, rid="r1", model_id="nemo")
    assert result is out


# ---------------------------------------------------------------------------
# Upstream reachability
# ---------------------------------------------------------------------------


def test_upstream_unreachable_returns_503(settings: Settings, auth_header: dict[str, str]) -> None:
    app = create_app(settings)
    with TestClient(app) as tc:
        req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
        tc.app.state.http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("refused", request=req),
        )
        r = tc.post(
            "/v1/agentic-rag/plan",
            headers=auth_header,
            json={"question": "q?"},
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runtime_unavailable"


# ---------------------------------------------------------------------------
# Gateway-enforced finalize helpers — called directly to guard regressions
# where Pydantic might be bypassed (e.g. model_construct)
# ---------------------------------------------------------------------------


def _build_chunks() -> list[EvidenceChunk]:
    return [
        EvidenceChunk.model_construct(
            chunk_id="c1", source_id="s1", text="t1", title=None, metadata=None
        ),
    ]


def test_finalize_plan_rejects_duplicate_rounds() -> None:
    body = RagPlanRequestBody.model_construct(
        question="q?",
        user_intent=None,
        available_sources=[],
        constraints=None,
    )
    out = RagPlanResponseBody.model_validate(
        {
            "intent": "q",
            "needs_rag": True,
            "required_facts": [],
            "retrieval_rounds": [
                {"round": 1, "queries": ["a"], "tools": ["vector_search"]},
                {"round": 1, "queries": ["b"], "tools": ["vector_search"]},
            ],
        }
    )
    with pytest.raises(HTTPException) as ei:
        _finalize_plan_response(body, out, rid="r1", model_id="nemo")
    assert ei.value.status_code == 502


def test_finalize_synthesize_accepts_valid_citations() -> None:
    chunks = _build_chunks()
    body = RagSynthesizeRequestBody.model_construct(
        question="q?",
        evidence_chunks=chunks,
        answer_style=None,
        require_citations=True,
        max_tokens=1024,
    )
    out = RagSynthesizeResponseBody.model_validate(
        {
            "answer": "ok",
            "citations": [{"source_id": "s1", "chunk_id": "c1", "claim": "alpha"}],
            "unsupported_claims": [],
            "confidence": "medium",
            "needs_more_retrieval": False,
        }
    )
    result = _finalize_synthesize_response(body, out, rid="r1", model_id="nemo")
    assert result is out


def test_finalize_evaluate_accepts_valid_chunk_ids() -> None:
    chunks = _build_chunks()
    body = RagEvaluateRequestBody.model_construct(
        question="q?",
        evidence_chunks=chunks,
        required_facts=[],
    )
    out = RagEvaluateResponseBody.model_validate(
        {
            "sufficient": False,
            "missing_facts": ["f"],
            "contradictions": [{"summary": "x", "chunk_ids": ["c1"]}],
            "recommended_followup_queries": [],
            "confidence": "low",
        }
    )
    result = _finalize_evaluate_response(body, out, rid="r1", model_id="nemo")
    assert result is out


def test_finalize_finalize_rejects_duplicate_markers() -> None:
    chunks = _build_chunks()
    body = RagFinalizeRequestBody.model_construct(
        question="q?",
        draft_answer="d",
        evidence_chunks=chunks,
        verification=None,
        format=None,
        citation_style=None,
        answer_style=None,
    )
    out = RagFinalizeResponseBody.model_validate(
        {
            "final_answer": "done",
            "citations": [
                {"marker": "1", "source_id": "s1", "chunk_id": "c1", "claim": "a"},
                {"marker": "1", "source_id": "s1", "chunk_id": "c1", "claim": "a"},
            ],
            "removed_unsupported_claims": [],
            "flagged_contradictions": [],
            "confidence": "high",
            "ready_for_user": True,
        }
    )
    with pytest.raises(HTTPException) as ei:
        _finalize_finalize_response(
            body,
            out,
            rid="r1",
            model_id="nemo",
            effective_citation_style="inline",
        )
    assert ei.value.status_code == 502
