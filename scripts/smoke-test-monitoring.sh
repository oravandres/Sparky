#!/usr/bin/env bash
# Smoke-test the Sparky monitoring stack — see PLAN.md §19, §21.
#
# Verifies:
#   1. node_exporter at :9100/metrics returns 200 and Prometheus exposition
#   2. gateway /metrics returns 401 unauthenticated and 200 with Bearer
#   3. dcgm-exporter at :9400/metrics returns 200 (only when
#      ENABLE_GPU_EXPORTER=true; skipped otherwise)
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-monitoring.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-monitoring.sh
#   SPARKY_NODE_EXPORTER_URL=http://127.0.0.1:9100 ./scripts/smoke-test-monitoring.sh
#   SPARKY_DCGM_EXPORTER_URL=http://127.0.0.1:9400 ./scripts/smoke-test-monitoring.sh
#   ENABLE_GPU_EXPORTER=false ./scripts/smoke-test-monitoring.sh   # skip DCGM
#
# All defaults use 127.0.0.1 so this runs locally on the appliance.

set -euo pipefail

GATEWAY_URL="${SPARKY_GATEWAY_URL:-http://127.0.0.1:8080}"
NODE_EXPORTER_URL="${SPARKY_NODE_EXPORTER_URL:-http://127.0.0.1:9100}"
DCGM_EXPORTER_URL="${SPARKY_DCGM_EXPORTER_URL:-http://127.0.0.1:9400}"
API_KEY="${SPARKY_API_KEY:-}"
ENABLE_GPU_EXPORTER="${ENABLE_GPU_EXPORTER:-true}"

if [[ -z "${API_KEY}" ]]; then
  echo "error: SPARKY_API_KEY must be set" >&2
  exit 1
fi

ok() { printf '  ok  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; exit 1; }

http_status() {
  curl --silent --output /dev/null --max-time 10 \
       --write-out '%{http_code}' \
       "$@"
}

http_body() {
  curl --silent --max-time 10 "$@"
}

echo "→ checking node_exporter ${NODE_EXPORTER_URL}"
status=$(http_status "${NODE_EXPORTER_URL}/metrics")
[[ "${status}" == "200" ]] || fail "node_exporter /metrics returned ${status}"
body=$(http_body "${NODE_EXPORTER_URL}/metrics")
echo "${body}" | head -n 200 | grep -q '^node_' \
  || fail "node_exporter payload missing node_* metrics"
ok "node_exporter /metrics = 200 with node_* metrics"

echo "→ checking gateway ${GATEWAY_URL}"
status=$(http_status "${GATEWAY_URL}/metrics")
[[ "${status}" == "401" ]] \
  || fail "gateway /metrics without auth returned ${status} (expected 401)"
ok "gateway /metrics without auth = 401"

status=$(http_status -H "Authorization: Bearer ${API_KEY}" "${GATEWAY_URL}/metrics")
[[ "${status}" == "200" ]] \
  || fail "gateway /metrics with auth returned ${status} (expected 200)"
body=$(http_body -H "Authorization: Bearer ${API_KEY}" "${GATEWAY_URL}/metrics")
echo "${body}" | head -n 200 | grep -q '^sparky_gateway_' \
  || fail "gateway /metrics payload missing sparky_gateway_* series"
ok "gateway /metrics with auth = 200 with sparky_gateway_* series"

if [[ "${ENABLE_GPU_EXPORTER}" == "true" ]] || [[ "${ENABLE_GPU_EXPORTER}" == "1" ]]; then
  echo "→ checking dcgm-exporter ${DCGM_EXPORTER_URL}"
  status=$(http_status "${DCGM_EXPORTER_URL}/metrics")
  [[ "${status}" == "200" ]] || fail "dcgm-exporter /metrics returned ${status}"
  body=$(http_body "${DCGM_EXPORTER_URL}/metrics")
  echo "${body}" | head -n 200 | grep -q '^DCGM_' \
    || fail "dcgm-exporter payload missing DCGM_* metrics"
  ok "dcgm-exporter /metrics = 200 with DCGM_* metrics"
else
  echo "  skip  dcgm-exporter (ENABLE_GPU_EXPORTER=${ENABLE_GPU_EXPORTER})"
fi

echo "OK — Sparky monitoring surface is up."
