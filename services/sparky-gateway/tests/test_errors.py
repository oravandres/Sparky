"""Error envelope + 404 handling (matches OpenAPI Error schema)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app


def test_unknown_route_returns_envelope(client: TestClient) -> None:
    r = client.get("/v1/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "http_error"
    assert "request_id" in body["error"]


def test_unhandled_exception_returns_internal_error_envelope(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/__test_boom")
    def boom() -> None:
        raise RuntimeError("intentional test failure")

    with TestClient(app, raise_server_exceptions=False) as tc:
        r = tc.get("/__test_boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error"
    assert "request_id" in body["error"]


def test_openapi_surface_disabled_by_default(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as tc:
        assert tc.get("/openapi.json").status_code == 404
        assert tc.get("/docs").status_code == 404


def test_openapi_surface_enabled_when_configured(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"sparky_enable_openapi_docs": True}))
    with TestClient(app) as tc:
        assert tc.get("/openapi.json").status_code == 200
