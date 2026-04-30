"""POST /v1/coding/* — Nemotron-backed coding intelligence (PLAN §5.4, §15)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sparky_gateway.coding_routes import (
    CodingFileIn,
    CodingReviewRequestBody,
    CodingReviewResponseBody,
    _finalize_coding_response,
)
from sparky_gateway.config import Settings
from sparky_gateway.main import create_app

_SAMPLE_FILE_CONTENT = "line 1\nline 2\nline 3\n"
_FILES = [
    {"path": "app/foo.py", "content": _SAMPLE_FILE_CONTENT},
    {"path": "app/bar.py", "content": "line 1\nline 2\n"},
]

_REVIEW_OK: dict[str, Any] = {
    "summary": "Looks fine.",
    "findings": [
        {
            "severity": "nit",
            "path": "app/foo.py",
            "line": 2,
            "title": "Consider naming",
            "explanation": "Local var could be clearer.",
            "recommendation": "Rename to `total`.",
        },
    ],
    "architecture_notes": [],
    "tests_to_add": ["test_foo_total"],
    "final_recommendation": "approve",
}

_REVIEW_OK_NO_FILES: dict[str, Any] = {
    "summary": "High-level design looks sound.",
    "findings": [],
    "architecture_notes": ["Keep the gateway thin."],
    "tests_to_add": [],
    "final_recommendation": "approve",
}

_REVIEW_CRITICAL: dict[str, Any] = {
    "summary": "Has a critical bug.",
    "findings": [
        {
            "severity": "critical",
            "path": "app/foo.py",
            "line": 1,
            "title": "Unchecked input",
            "explanation": "User input flows into sql raw.",
            "recommendation": "Parameterize.",
        },
    ],
    "architecture_notes": [],
    "tests_to_add": [],
    "final_recommendation": "request_changes",
}


def _mock_upstream(content: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(content)}}]}
    return resp


# ---------------------------------------------------------------------------
# Auth + schema gates (4 routes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/v1/coding/review",
        "/v1/coding/architecture",
        "/v1/coding/refactor-plan",
        "/v1/coding/security-review",
    ],
)
def test_coding_requires_auth(client: TestClient, path: str) -> None:
    r = client.post(path, json={"task": "review", "instructions": "check"})
    assert r.status_code == 401


def test_review_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "instructions": "x", "unexpected": True},
    )
    assert r.status_code == 422


def test_review_requires_task_field(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"instructions": "x"},
    )
    assert r.status_code == 422


def test_review_requires_some_content(client: TestClient, auth_header: dict[str, str]) -> None:
    """files=[], diff=None, instructions=None → 422 (nothing to review)."""
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review"},
    )
    assert r.status_code == 422


def test_review_rejects_duplicate_file_paths(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={
            "task": "review",
            "files": [
                {"path": "a.py", "content": "x"},
                {"path": "a.py", "content": "y"},
            ],
        },
    )
    assert r.status_code == 422


def test_review_rejects_invalid_task_value(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "not-a-task", "instructions": "x"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Route → allowed task mapping
# ---------------------------------------------------------------------------


def test_review_accepts_debug_task(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "debug", "instructions": "why does X fail?"},
    )
    assert r.status_code == 200


def test_architecture_rejects_review_task(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/coding/architecture",
        headers=auth_header,
        json={"task": "review", "instructions": "x"},
    )
    assert r.status_code == 422


def test_refactor_plan_rejects_security_review_task(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/coding/refactor-plan",
        headers=auth_header,
        json={"task": "security-review", "instructions": "x"},
    )
    assert r.status_code == 422


def test_security_review_rejects_architecture_task(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/coding/security-review",
        headers=auth_header,
        json={"task": "architecture", "instructions": "x"},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Happy paths — the gateway proxies, validates JSON, returns strict output
# ---------------------------------------------------------------------------


def test_review_happy_path_with_files(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_OK))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES, "language": "python"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_recommendation"] == "approve"
    assert body["findings"][0]["severity"] == "nit"
    assert body["tests_to_add"] == ["test_foo_total"]


def test_architecture_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    r = client.post(
        "/v1/coding/architecture",
        headers=auth_header,
        json={"task": "architecture", "instructions": "review overall structure"},
    )
    assert r.status_code == 200
    assert r.json()["architecture_notes"] == ["Keep the gateway thin."]


def test_refactor_plan_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    r = client.post(
        "/v1/coding/refactor-plan",
        headers=auth_header,
        json={"task": "refactor-plan", "diff": "--- a\n+++ b\n@@\n-foo\n+bar\n"},
    )
    assert r.status_code == 200


def test_security_review_happy_path(client: TestClient, auth_header: dict[str, str]) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    r = client.post(
        "/v1/coding/security-review",
        headers=auth_header,
        json={
            "task": "security-review",
            "files": _FILES,
            "instructions": "look for SQLi and path traversal",
        },
    )
    assert r.status_code == 200


def test_review_honors_caller_max_tokens_cap(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Caller-supplied max_tokens is clamped to the operator ceiling, not
    rejected when above it. The upstream payload should receive the min."""
    post_mock = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    client.app.state.http_client.post = post_mock
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "instructions": "x", "max_tokens": 8192},
    )
    assert r.status_code == 200
    sent_payload = post_mock.await_args.kwargs["json"]
    # Settings default sparky_coding_max_tokens=4096; clamp to that
    assert sent_payload["max_tokens"] == 4096


def test_review_respects_caller_below_cap(client: TestClient, auth_header: dict[str, str]) -> None:
    post_mock = AsyncMock(return_value=_mock_upstream(_REVIEW_OK_NO_FILES))
    client.app.state.http_client.post = post_mock
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "instructions": "x", "max_tokens": 256},
    )
    assert r.status_code == 200
    sent_payload = post_mock.await_args.kwargs["json"]
    assert sent_payload["max_tokens"] == 256


# ---------------------------------------------------------------------------
# Model-side failure modes — gateway returns 502
# ---------------------------------------------------------------------------


def test_review_502_on_invalid_json(client: TestClient, auth_header: dict[str, str]) -> None:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "application/json"}
    resp.json.return_value = {"choices": [{"message": {"content": "not json"}}]}
    client.app.state.http_client.post = AsyncMock(return_value=resp)
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "instructions": "x"},
    )
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "runtime_error"


def test_review_502_when_finding_path_unknown(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_REVIEW_OK)
    bad["findings"] = [
        {
            "severity": "low",
            "path": "ghost/file.py",
            "line": 1,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 502


def test_review_502_when_finding_line_out_of_range(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """app/foo.py has 3 lines; line=99 must be rejected."""
    bad = dict(_REVIEW_OK)
    bad["findings"] = [
        {
            "severity": "low",
            "path": "app/foo.py",
            "line": 99,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 502


def test_review_502_when_approve_despite_critical(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """final_recommendation=approve with a critical finding violates PLAN §15."""
    bad = dict(_REVIEW_CRITICAL)
    bad["final_recommendation"] = "approve"
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 502


def test_review_accepts_critical_with_request_changes(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(_REVIEW_CRITICAL))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 200
    assert r.json()["final_recommendation"] == "request_changes"


def test_review_502_when_severity_is_invalid(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_REVIEW_OK)
    bad["findings"] = [
        {
            "severity": "blocker",
            "path": "app/foo.py",
            "line": 1,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 502


def test_review_502_when_final_recommendation_invalid(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    bad = dict(_REVIEW_OK)
    bad["final_recommendation"] = "lgtm"
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "instructions": "run"},
    )
    assert r.status_code == 502


def test_review_ignores_path_check_when_diff_only(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Diff-only reviews cannot be path-checked; findings[].path is accepted."""
    ok = dict(_REVIEW_OK_NO_FILES)
    ok["findings"] = [
        {
            "severity": "low",
            "path": "somewhere/else.py",
            "line": 1,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "diff": "--- a\n+++ b\n"},
    )
    assert r.status_code == 200


def test_review_accepts_null_path_when_files_supplied(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Cross-cutting findings (path=null) are always allowed."""
    ok = dict(_REVIEW_OK)
    ok["findings"] = [
        {
            "severity": "medium",
            "path": None,
            "line": None,
            "title": "Cross-cutting concern",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": _FILES},
    )
    assert r.status_code == 200


def test_review_accepts_empty_file_content(client: TestClient, auth_header: dict[str, str]) -> None:
    """Empty `__init__.py` / `.gitkeep` files are legitimate snapshot entries."""
    empty_files = [
        {"path": "pkg/__init__.py", "content": ""},
        {"path": ".gitkeep", "content": ""},
    ]
    ok = dict(_REVIEW_OK_NO_FILES)
    ok["findings"] = []
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": empty_files},
    )
    assert r.status_code == 200


def test_review_line_one_valid_for_empty_file_content(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Empty content must be treated as a one-line file for the line bound."""
    empty_files = [{"path": "empty.py", "content": ""}]
    ok = dict(_REVIEW_OK_NO_FILES)
    ok["findings"] = [
        {
            "severity": "nit",
            "path": "empty.py",
            "line": 1,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(ok))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": empty_files},
    )
    assert r.status_code == 200


def test_review_502_line_two_rejected_for_empty_file_content(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Empty file content has no line 2; the gateway must still reject."""
    empty_files = [{"path": "empty.py", "content": ""}]
    bad = dict(_REVIEW_OK_NO_FILES)
    bad["findings"] = [
        {
            "severity": "nit",
            "path": "empty.py",
            "line": 2,
            "title": "t",
            "explanation": "e",
            "recommendation": "r",
        },
    ]
    client.app.state.http_client.post = AsyncMock(return_value=_mock_upstream(bad))
    r = client.post(
        "/v1/coding/review",
        headers=auth_header,
        json={"task": "review", "files": empty_files},
    )
    assert r.status_code == 502


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
            "/v1/coding/review",
            headers=auth_header,
            json={"task": "review", "instructions": "x"},
        )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runtime_unavailable"


# ---------------------------------------------------------------------------
# Direct helper calls — keep the invariants even if Pydantic is bypassed
# ---------------------------------------------------------------------------


def _build_body(files: list[CodingFileIn] | None = None) -> CodingReviewRequestBody:
    return CodingReviewRequestBody.model_construct(
        task="review",
        repository=None,
        language=None,
        files=files or [],
        diff=None,
        instructions="x",
        max_tokens=None,
    )


def test_finalize_rejects_approve_with_critical() -> None:
    body = _build_body()
    out = CodingReviewResponseBody.model_validate(
        {
            "summary": "s",
            "findings": [
                {
                    "severity": "critical",
                    "title": "t",
                    "explanation": "e",
                    "recommendation": "r",
                },
            ],
            "architecture_notes": [],
            "tests_to_add": [],
            "final_recommendation": "approve",
        }
    )
    with pytest.raises(HTTPException) as ei:
        _finalize_coding_response(body, out, rid="r1", model_id="nemo", task="review")
    assert ei.value.status_code == 502


def test_finalize_rejects_unknown_path_when_files_supplied() -> None:
    files = [
        CodingFileIn.model_construct(path="a.py", content="x\n"),
    ]
    body = _build_body(files=files)
    out = CodingReviewResponseBody.model_validate(
        {
            "summary": "s",
            "findings": [
                {
                    "severity": "low",
                    "path": "b.py",
                    "line": 1,
                    "title": "t",
                    "explanation": "e",
                    "recommendation": "r",
                },
            ],
            "architecture_notes": [],
            "tests_to_add": [],
            "final_recommendation": "request_changes",
        }
    )
    with pytest.raises(HTTPException) as ei:
        _finalize_coding_response(body, out, rid="r1", model_id="nemo", task="review")
    assert ei.value.status_code == 502


def test_finalize_accepts_line_at_boundary() -> None:
    files = [CodingFileIn.model_construct(path="a.py", content="l1\nl2\nl3\n")]
    body = _build_body(files=files)
    out = CodingReviewResponseBody.model_validate(
        {
            "summary": "s",
            "findings": [
                {
                    "severity": "low",
                    "path": "a.py",
                    "line": 3,
                    "title": "t",
                    "explanation": "e",
                    "recommendation": "r",
                },
            ],
            "architecture_notes": [],
            "tests_to_add": [],
            "final_recommendation": "approve",
        }
    )
    result = _finalize_coding_response(body, out, rid="r1", model_id="nemo", task="review")
    assert result is out


def test_finalize_accepts_empty_file_content_line_one() -> None:
    """A 1-line file (no newline) must allow line=1 without a false 502."""
    files = [CodingFileIn.model_construct(path="a.py", content="only-line")]
    body = _build_body(files=files)
    out = CodingReviewResponseBody.model_validate(
        {
            "summary": "s",
            "findings": [
                {
                    "severity": "low",
                    "path": "a.py",
                    "line": 1,
                    "title": "t",
                    "explanation": "e",
                    "recommendation": "r",
                },
            ],
            "architecture_notes": [],
            "tests_to_add": [],
            "final_recommendation": "approve",
        }
    )
    result = _finalize_coding_response(body, out, rid="r1", model_id="nemo", task="review")
    assert result is out
