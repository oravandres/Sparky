"""Health/readiness probes (PLAN §5.1)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_is_unauthenticated_and_ok(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_ready_is_unauthenticated_and_reports_dependencies(client: TestClient) -> None:
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert "model_registry" in body["dependencies"]
    assert body["dependencies"]["model_registry"]["status"] == "ready"


def test_ready_not_ready_when_no_active_models(client_registry_no_active: TestClient) -> None:
    r = client_registry_no_active.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["model_registry"]["status"] == "not_ready"


def test_request_id_header_is_echoed(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers.get("X-Request-ID") == "abc-123"


def test_request_id_header_is_generated_when_missing(client: TestClient) -> None:
    r = client.get("/health")
    rid = r.headers.get("X-Request-ID")
    assert rid is not None and len(rid) >= 16
