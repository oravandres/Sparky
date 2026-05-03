"""POST /v1/chat/completions — registry gate + vLLM proxy (PLAN §5.1, §12)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "config" / "model-registry.yaml"
TEST_API_KEY = "test-key-not-for-production-use-only"


def test_chat_completions_requires_auth(client: TestClient) -> None:
    r = client.post(
        "/v1/chat/completions",
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 401


def test_chat_completions_rejects_unapproved_model(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unapproved_model"


def test_chat_completions_rejects_image_model(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={"model": "flux2-dev", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_model_for_route"


def test_chat_completions_rejects_stream_true(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )
    assert r.status_code == 422


def test_chat_completions_rejects_extra_openai_fields(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
            "max_completion_tokens": 128,
        },
    )
    assert r.status_code == 422


def test_chat_completions_enforces_message_count(
    settings: Settings, auth_header: dict[str, str]
) -> None:
    tight = settings.model_copy(
        update={"sparky_chat_max_messages": 2, "sparky_nemotron_max_inflight": 2}
    )
    app = create_app(tight)
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(3)]
    with TestClient(app) as tc:
        r = tc.post(
            "/v1/chat/completions",
            headers=auth_header,
            json={
                "model": "nemotron-3-super-120b-a12b-nvfp4",
                "messages": msgs,
            },
        )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


def test_chat_completions_proxies_json(client: TestClient, auth_header: dict[str, str]) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"id": "cmpl-1", "choices": []}
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert r.status_code == 200
    assert r.json() == {"id": "cmpl-1", "choices": []}
    post_mock = client.app.state.http_client.post
    assert post_mock.await_count == 1
    _args, kwargs = post_mock.call_args
    assert kwargs["json"]["model"] == "nemotron-3-super-120b-a12b-nvfp4"
    assert "max_completion_tokens" not in kwargs["json"]


def test_chat_completions_normalizes_upstream_error(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.headers = {"content-type": "text/plain"}
    mock_resp.text = "internal stack trace here"
    client.app.state.http_client.post = AsyncMock(return_value=mock_resp)

    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert r.status_code == 502
    body = r.json()
    assert body["error"]["code"] == "runtime_error"
    assert "request_id" in body["error"]


def test_chat_completions_runtime_unreachable(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    client.app.state.http_client.post = AsyncMock(
        side_effect=httpx.ConnectError("refused", request=req)
    )

    r = client.post(
        "/v1/chat/completions",
        headers=auth_header,
        json={
            "model": "nemotron-3-super-120b-a12b-nvfp4",
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert r.status_code == 503
    assert r.json()["error"]["code"] == "runtime_unavailable"


def test_chat_completions_payload_too_large(auth_header: dict[str, str], tmp_path: Path) -> None:
    settings = Settings(
        sparky_api_key=TEST_API_KEY,
        sparky_log_level="warning",
        sparky_model_registry_path=REGISTRY_PATH,
        sparky_logging_config_path=None,
        sparky_max_request_body_bytes=64,
        jobs_dir=tmp_path / "jobs",
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        r = tc.post(
            "/v1/chat/completions",
            headers=auth_header,
            json={
                "model": "nemotron-3-super-120b-a12b-nvfp4",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"
