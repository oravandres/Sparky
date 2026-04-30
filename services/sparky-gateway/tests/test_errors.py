"""Error envelope + 404 handling (matches OpenAPI Error schema)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_unknown_route_returns_envelope(client: TestClient) -> None:
    r = client.get("/v1/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "http_error"
    assert "request_id" in body["error"]
