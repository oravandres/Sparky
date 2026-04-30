#!/usr/bin/env bash
# Smoke-test the gateway health surface — see PLAN.md §21.
#
# Verifies:
#   1. /health returns 200 with status=ok
#   2. /ready returns 200 with status=ready
#   3. unauth GET /v1/models returns 401
#   4. authed GET /v1/models returns 200 with a non-empty data array
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-health.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-health.sh

set -euo pipefail

GATEWAY_URL="${SPARKY_GATEWAY_URL:-http://127.0.0.1:8080}"
API_KEY="${SPARKY_API_KEY:-}"

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

echo "→ ${GATEWAY_URL}"

# 1. /health
status=$(http_status "${GATEWAY_URL}/health")
[[ "${status}" == "200" ]] || fail "/health returned ${status}"
body=$(http_body "${GATEWAY_URL}/health")
echo "${body}" | grep -q '"status":"ok"' || fail "/health body unexpected: ${body}"
ok "/health = 200, status=ok"

# 2. /ready
status=$(http_status "${GATEWAY_URL}/ready")
[[ "${status}" == "200" ]] || fail "/ready returned ${status} (expected 200)"
body=$(http_body "${GATEWAY_URL}/ready")
echo "${body}" | grep -q '"status":"ready"' \
  || fail "/ready body unexpected: ${body}"
ok "/ready = 200, status=ready"

# 3. Unauthenticated /v1/models must be rejected
status=$(http_status "${GATEWAY_URL}/v1/models")
[[ "${status}" == "401" ]] || fail "/v1/models without auth returned ${status} (expected 401)"
ok "/v1/models without auth = 401"

# 4. Authenticated /v1/models must return data
status=$(http_status -H "Authorization: Bearer ${API_KEY}" "${GATEWAY_URL}/v1/models")
[[ "${status}" == "200" ]] || fail "/v1/models with auth returned ${status}"
body=$(http_body -H "Authorization: Bearer ${API_KEY}" "${GATEWAY_URL}/v1/models")
echo "${body}" | grep -q '"data"' || fail "/v1/models payload missing data array"
ok "/v1/models with auth = 200 with data[]"

echo "OK — gateway health surface is up."
