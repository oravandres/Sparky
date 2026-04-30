"""POST /v1/reasoning/* — structured outputs via Nemotron proxy (PLAN §5.2, §12)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app

_ANALYZE_OK = {
    "summary": "S",
    "key_points": ["a"],
    "risks": ["r"],
    "assumptions": ["asm"],
    "recommendation": "go",
    "confidence": "high",
}

_COMPARE_OK = {
    "scores": [
        {
            "option_id": "o1",
            "criterion_id": "c1",
            "score": 8.5,
            "rationale": "Good fit.",
        },
    ],
    "totals": [{"option_id": "o1", "weighted_total": 999}],
    "recommendation": {"option_id": "o1", "reasoning": "Best option.", "caveats": []},
    "confidence": "medium",
}

_COMPARE_TWO_CRITERIA = {
    "scores": [
        {
            "option_id": "o1",
            "criterion_id": "c1",
            "score": 8.0,
            "rationale": "Fast.",
        },
        {
            "option_id": "o1",
            "criterion_id": "c2",
            "score": 4.0,
            "rationale": "Costly.",
        },
    ],
    "totals": [],
    "recommendation": {"option_id": "o1", "reasoning": "Ok.", "caveats": []},
    "confidence": "high",
}


def test_reasoning_analyze_requires_auth(client: TestClient) -> None:
    r = client.post("/v1/reasoning/analyze", json={"task": "t"})
    assert r.status_code == 401


def test_reasoning_analyze_rejects_extra_fields(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/reasoning/analyze",
        headers=auth_header,
        json={"task": "x", "model": "nemotron-3-super-120b-a12b-nvfp4"},
    )
    assert r.status_code == 422


def test_reasoning_compare_rejects_extra_fields(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "q?",
            "options": [{"id": "a", "name": "A"}],
            "criteria": [{"id": "c", "name": "cost"}],
            "_bad": True,
        },
    )
    assert r.status_code == 422


def test_reasoning_analyze_proxies_and_validates_json(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    payload = {"choices": [{"message": {"content": json.dumps(_ANALYZE_OK)}}]}
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = payload
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/analyze",
        headers=auth_header,
        json={
            "task": "Evaluate the trade-off",
            "max_tokens": 512,
            "criteria": ["security", "cost"],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["summary"] == "S"
    assert data["confidence"] == "high"


def test_reasoning_analyze_502_when_model_json_invalid(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"summary":"only"}}'}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/analyze",
        headers=auth_header,
        json={"task": "t"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "runtime_error"


def test_reasoning_analyze_502_when_schema_mismatch(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"summary": "only"})}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/analyze",
        headers=auth_header,
        json={"task": "t"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "runtime_error"


def test_reasoning_compare_strip_json_fence(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    raw_content = "```json\n" + json.dumps(_COMPARE_OK) + "\n```"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": raw_content}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "Which stack?",
            "options": [{"id": "o1", "name": "One"}],
            "criteria": [{"id": "c1", "name": "Ops", "weight": 1.0}],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"]["option_id"] == "o1"
    assert body["totals"] == [{"option_id": "o1", "weighted_total": 8.5}]


def test_reasoning_upstream_unreachable(settings: Settings, auth_header: dict[str, str]) -> None:
    app = create_app(settings)
    with TestClient(app) as tc:
        tc.app.state.http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("refused"),
        )
        r = tc.post(
            "/v1/reasoning/analyze",
            headers=auth_header,
            json={"task": "t"},
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runtime_unavailable"


def test_reasoning_compare_recomputes_weighted_totals(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Gateway overwrites model totals using score * weight sums."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(_COMPARE_TWO_CRITERIA)}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "Pick?",
            "options": [{"id": "o1", "name": "One"}],
            "criteria": [
                {"id": "c1", "name": "Speed", "weight": 2.0},
                {"id": "c2", "name": "Cost", "weight": 0.5},
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["totals"] == [{"option_id": "o1", "weighted_total": 18.0}]


def test_reasoning_compare_502_incomplete_score_matrix(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = {
        "scores": [_COMPARE_TWO_CRITERIA["scores"][0]],
        "totals": [],
        "recommendation": _COMPARE_TWO_CRITERIA["recommendation"],
        "confidence": "high",
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(bad)}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "Pick?",
            "options": [{"id": "o1", "name": "One"}],
            "criteria": [
                {"id": "c1", "name": "Speed"},
                {"id": "c2", "name": "Cost"},
            ],
        },
    )
    assert r.status_code == 502


def test_reasoning_compare_502_bad_recommended_option(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    corrupt = dict(_COMPARE_OK)
    corrupt["recommendation"] = {
        "option_id": "unknown",
        "reasoning": "x",
        "caveats": [],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(corrupt)}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "?",
            "options": [{"id": "o1", "name": "One"}],
            "criteria": [{"id": "c1", "name": "X"}],
        },
    )
    assert r.status_code == 502


def test_reasoning_compare_502_score_out_of_bounds(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad_score = dict(_COMPARE_OK)
    bad_score["scores"] = [
        dict(_COMPARE_OK["scores"][0]),
    ]
    bad_score["scores"][0]["score"] = 42.0
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(bad_score)}}],
    }
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/reasoning/compare",
        headers=auth_header,
        json={
            "question": "?",
            "options": [{"id": "o1", "name": "One"}],
            "criteria": [{"id": "c1", "name": "X"}],
        },
    )
    assert r.status_code == 502
