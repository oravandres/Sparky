#!/usr/bin/env bash
# Start the Nemotron 3 Super vLLM runtime via Docker Compose — PLAN §13.1.
# Expects /etc/sparky/sparky.env with HF_TOKEN populated (gated model).
#
# Usage:
#   ./scripts/start-nemotron-vllm.sh up -d
#   ./scripts/start-nemotron-vllm.sh logs -f
#   ./scripts/start-nemotron-vllm.sh down
#
# Requires the reasoning parser already on disk. Run
# scripts/download-nemotron-parser.sh once before the first up.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SPARKY_ENV_FILE:-/etc/sparky/sparky.env}"
COMPOSE_FILE="${REPO_ROOT}/docker/compose/docker-compose.nemotron.yml"
PARSER_PATH="${SPARKY_NEMOTRON_PARSER_PATH:-/opt/sparky/config/nemotron/super_v3_reasoning_parser.py}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} not found." >&2
  echo "Create it from config/sparky.env.example with HF_TOKEN populated" >&2
  echo "(PLAN §10 — gated Hugging Face repo)." >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "error: compose file missing at ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${PARSER_PATH}" ]]; then
  echo "error: reasoning parser missing at ${PARSER_PATH}" >&2
  echo "Run scripts/download-nemotron-parser.sh first." >&2
  exit 1
fi

if ! grep -E '^HF_TOKEN=.+' "${ENV_FILE}" >/dev/null 2>&1; then
  echo "error: HF_TOKEN is empty or missing in ${ENV_FILE}" >&2
  echo "The Nemotron 3 Super weights are gated; an HF token is required (PLAN §10)." >&2
  exit 1
fi

export SPARKY_ENV_FILE="${ENV_FILE}"
exec docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
