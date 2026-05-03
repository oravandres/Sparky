"""Health/readiness probes (PLAN §5.1)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app


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
    # Phase 7 wiring: jobs_dir is also surfaced so deployments can detect a
    # missing bind mount before submissions return 503.
    assert "jobs_dir" in body["dependencies"]
    assert body["dependencies"]["jobs_dir"]["status"] == "ready"


def test_ready_not_ready_when_no_active_models(client_registry_no_active: TestClient) -> None:
    r = client_registry_no_active.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["model_registry"]["status"] == "not_ready"


def test_ready_not_ready_when_jobs_dir_missing(tmp_path: Path) -> None:
    """Mirrors the read-only-container / missing-bind-mount case: /health
    keeps working but /ready is 503 with a clear `jobs_dir` detail so MiMi
    monitoring catches the misconfiguration before a media submission does."""
    settings = Settings(
        sparky_api_key="test-key-not-for-production-use-only",
        sparky_log_level="warning",
        sparky_model_registry_path=Path(__file__).resolve().parents[3]
        / "config"
        / "model-registry.yaml",
        sparky_logging_config_path=None,
        # Intentionally a path that does not exist — JobStore must not have
        # created it at boot.
        jobs_dir=tmp_path / "missing" / "jobs",
    )
    app = create_app(settings)
    with TestClient(app) as tc:
        # /health stays green even when jobs_dir is missing.
        assert tc.get("/health").status_code == 200
        ready = tc.get("/ready")
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["jobs_dir"]["status"] == "not_ready"
    assert "missing or not writable" in body["dependencies"]["jobs_dir"]["detail"]


def test_request_id_header_is_echoed(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert r.headers.get("X-Request-ID") == "abc-123"


def test_request_id_header_is_generated_when_missing(client: TestClient) -> None:
    r = client.get("/health")
    rid = r.headers.get("X-Request-ID")
    assert rid is not None and len(rid) >= 16
