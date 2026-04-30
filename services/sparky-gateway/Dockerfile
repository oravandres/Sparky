# syntax=docker/dockerfile:1.7
# sparky-gateway image — see PLAN.md §11 (containers) and §12 (gateway).
# Runs as non-root, refuses to boot without SPARKY_API_KEY (PLAN §10).

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# Build dependencies isolated to a builder stage so the runtime image stays slim.
FROM base AS builder

WORKDIR /build
COPY services/sparky-common/ ./sparky-common/
COPY services/sparky-gateway/ ./sparky-gateway/

RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /wheels ./sparky-common ./sparky-gateway

FROM base AS runtime

# unprivileged user — uid/gid match the host `sparky` service user (PLAN §10).
ARG SPARKY_UID=10001
ARG SPARKY_GID=10001
RUN groupadd --system --gid "$SPARKY_GID" sparky \
 && useradd --system --uid "$SPARKY_UID" --gid "$SPARKY_GID" \
        --home-dir /home/sparky --create-home --shell /usr/sbin/nologin sparky

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-deps /wheels/*.whl \
 && pip install \
        "fastapi>=0.115,<0.116" \
        "uvicorn[standard]>=0.32,<0.33" \
        "pydantic>=2.9,<3" \
        "pydantic-settings>=2.6,<3" \
        "httpx>=0.27,<0.28" \
        "prometheus-client>=0.21,<0.22" \
        "PyYAML>=6.0,<7" \
        "python-json-logger>=2.0,<3" \
 && rm -rf /wheels

ENV SPARKY_GATEWAY_BIND=0.0.0.0:8080 \
    SPARKY_LOG_LEVEL=info \
    SPARKY_MODEL_REGISTRY_PATH=/opt/sparky/config/model-registry.yaml \
    SPARKY_LOGGING_CONFIG_PATH=/opt/sparky/config/logging.yaml

USER sparky:sparky
EXPOSE 8080

# Use uvicorn's --factory mode so create_app() runs once per process and
# fails loudly if SPARKY_API_KEY is missing (PLAN §10).
CMD ["uvicorn", "--factory", "sparky_gateway.main:create_app", \
     "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
