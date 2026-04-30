"""API-key authentication (PLAN §10, §12)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app


def test_models_requires_authorization_header(client: TestClient) -> None:
    r = client.get("/v1/models")
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"
    assert "request_id" in body["error"]
    assert r.headers.get("WWW-Authenticate") == "Bearer"


def test_models_rejects_wrong_scheme(client: TestClient) -> None:
    r = client.get("/v1/models", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_models_rejects_wrong_key(client: TestClient) -> None:
    r = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_models_accepts_correct_key(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get("/v1/models", headers=auth_header)
    assert r.status_code == 200


def test_metrics_requires_authorization(client: TestClient) -> None:
    r = client.get("/metrics")
    assert r.status_code == 401


def test_metrics_accepts_correct_key(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get("/metrics", headers=auth_header)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_create_app_rejects_empty_api_key(settings: Settings) -> None:
    settings.sparky_api_key = ""
    with pytest.raises(RuntimeError, match="SPARKY_API_KEY"):
        create_app(settings)
