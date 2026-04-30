#!/usr/bin/env bash
# Start the Sparky Gateway via Docker Compose. See PLAN.md §12.
# Expects /etc/sparky/sparky.env to exist (mirrored from MiMi-Secrets sealed
# secret 'sparky-api-key' per PLAN §10).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SPARKY_ENV_FILE:-/etc/sparky/sparky.env}"
COMPOSE_FILE="${REPO_ROOT}/docker/compose/docker-compose.gateway.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} not found." >&2
  echo "Create it from config/sparky.env.example and source SPARKY_API_KEY" >&2
  echo "from the MiMi-Secrets sealed secret 'sparky-api-key' (PLAN §10)." >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "error: compose file missing at ${COMPOSE_FILE}" >&2
  exit 1
fi

export SPARKY_ENV_FILE="${ENV_FILE}"
exec docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
