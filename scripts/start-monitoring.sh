#!/usr/bin/env bash
# Start the Sparky monitoring stack via Docker Compose.
# See PLAN.md §4.1, §19.
#
# Brings up node_exporter on :9100 always, and DCGM exporter on :9400
# when ENABLE_GPU_EXPORTER=true (set in /etc/sparky/sparky.env per PLAN
# §7.4). Pass the same arguments you would to `docker compose`:
#
#   ./scripts/start-monitoring.sh up -d
#   ./scripts/start-monitoring.sh logs -f
#   ./scripts/start-monitoring.sh down
#
# The env file path can be overridden via SPARKY_ENV_FILE.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${SPARKY_ENV_FILE:-/etc/sparky/sparky.env}"
COMPOSE_FILE="${REPO_ROOT}/docker/compose/docker-compose.monitoring.yml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: ${ENV_FILE} not found." >&2
  echo "Create it from config/sparky.env.example. ENABLE_GPU_EXPORTER=true" >&2
  echo "activates the DCGM exporter; see PLAN §7.4 / §19." >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "error: compose file missing at ${COMPOSE_FILE}" >&2
  exit 1
fi

# Read ENABLE_GPU_EXPORTER from the env file without sourcing it (avoid
# leaking secrets into this shell). Default to "true" to match
# config/sparky.env.example.
gpu_flag="$(grep -E '^ENABLE_GPU_EXPORTER=' "${ENV_FILE}" \
  | tail -n 1 \
  | cut -d= -f2- \
  | tr -d '"' \
  | tr -d "'" \
  | tr -d '[:space:]' \
  || true)"
gpu_flag="${gpu_flag:-true}"

profile_args=()
if [[ "${gpu_flag}" == "true" ]] || [[ "${gpu_flag}" == "1" ]]; then
  profile_args+=(--profile gpu)
  echo "info: ENABLE_GPU_EXPORTER=${gpu_flag} — DCGM exporter enabled"
else
  echo "info: ENABLE_GPU_EXPORTER=${gpu_flag} — DCGM exporter disabled"
fi

export SPARKY_ENV_FILE="${ENV_FILE}"
exec docker compose \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  "${profile_args[@]}" \
  "$@"
