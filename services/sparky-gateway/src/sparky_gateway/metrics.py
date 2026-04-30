"""Prometheus metrics — PLAN.md §5.1, §19.

Per `config/api-contract.yaml`, `GET /metrics` requires the API key — MiMi
Prometheus scrapes Sparky with Bearer auth.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse

from .auth import verify_api_key

REGISTRY = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "sparky_gateway_requests_total",
    "Total HTTP requests handled by the gateway",
    labelnames=("method", "route", "status"),
    registry=REGISTRY,
)

REQUEST_LATENCY_SECONDS = Histogram(
    "sparky_gateway_request_duration_seconds",
    "Request latency in seconds",
    labelnames=("method", "route"),
    registry=REGISTRY,
)


def _route_template(request: Request) -> str:
    """Use the matched route template when available to bound metric cardinality.

    Falls back to the literal path; for Phase 3 the route set is small.
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return str(route.path)
    return request.url.path


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[StarletteResponse]],
    ) -> StarletteResponse:
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start

        route = _route_template(request)
        REQUEST_LATENCY_SECONDS.labels(method=request.method, route=route).observe(elapsed)
        REQUESTS_TOTAL.labels(
            method=request.method, route=route, status=str(response.status_code)
        ).inc()
        return response


router = APIRouter(tags=["metrics"])


@router.get("/metrics", dependencies=[Depends(verify_api_key)])
def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
