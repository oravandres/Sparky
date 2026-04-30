"""POST /v1/chat/completions — registry gate + vLLM proxy (PLAN §5.1, §12)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from fastapi.testclient import TestClient


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


def test_chat_completions_proxies_json(client: TestClient, auth_header: dict[str, str]) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "application/json"}
    mock_resp.json.return_value = {"id": "cmpl-1", "choices": []}
    mock_instance = MagicMock()
    mock_instance.post.return_value = mock_resp

    with patch("sparky_gateway.chat_routes.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value = mock_instance
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
    mock_instance.post.assert_called_once()
    _args, kwargs = mock_instance.post.call_args
    assert kwargs["json"]["model"] == "nemotron-3-super-120b-a12b-nvfp4"


def test_chat_completions_runtime_unreachable(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    req = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")

    with patch("sparky_gateway.chat_routes.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.side_effect = httpx.ConnectError("refused", request=req)
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
