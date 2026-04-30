"""GET /metrics — Prometheus exposition (PLAN §5.1, §19)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_metrics_exposition_format(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get("/metrics", headers=auth_header)
    assert r.status_code == 200
    body = r.text
    assert "sparky_gateway_requests_total" in body
    assert "sparky_gateway_request_duration_seconds" in body


def test_metrics_increment_after_traffic(client: TestClient, auth_header: dict[str, str]) -> None:
    client.get("/health")
    client.get("/health")
    r = client.get("/metrics", headers=auth_header)
    body = r.text
    assert 'route="/health"' in body
    assert 'method="GET"' in body


def test_metrics_unmatched_route_uses_bounded_label(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    client.get("/v1/no-such-route-for-metrics-cardinality-test")
    r = client.get("/metrics", headers=auth_header)
    assert 'route="__unmatched__"' in r.text
