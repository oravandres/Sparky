#!/usr/bin/env bash
# Smoke-test the /v1/coding/* endpoints against a running gateway —
# see PLAN.md §15 and §21.
#
# Verifies:
#   1. unauth POST /v1/coding/review     returns 401
#   2. POST /v1/coding/review            returns 200 with a structured body
#   3. POST /v1/coding/architecture      returns 200 for task=architecture
#   4. POST /v1/coding/refactor-plan     returns 200 for task=refactor-plan
#   5. POST /v1/coding/security-review   returns 200 for task=security-review
#   6. Task/route mismatch               returns 422
#
# Requires `jq` in PATH. Requires the Nemotron text runtime to be reachable
# from the gateway (raw 127.0.0.1:8000 per PLAN §4.1) or the calls will
# return 503 `runtime_unavailable` — which is still a valid proxy signal
# but not a green smoke-test.
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-coding.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-coding.sh

set -euo pipefail

GATEWAY_URL="${SPARKY_GATEWAY_URL:-http://127.0.0.1:8080}"
API_KEY="${SPARKY_API_KEY:-}"

if [[ -z "${API_KEY}" ]]; then
  echo "error: SPARKY_API_KEY must be set" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "error: jq is required" >&2
  exit 1
fi

ok() { printf '  ok  %s\n' "$1"; }
fail() { printf '  FAIL  %s\n' "$1" >&2; exit 1; }

http_status() {
  curl --silent --output /dev/null --max-time 30 \
       --write-out '%{http_code}' \
       "$@"
}

http_body() {
  curl --silent --max-time 30 "$@"
}

post_json() {
  local path="$1"
  local data="$2"
  shift 2
  curl --silent --max-time 30 \
       -H "Authorization: Bearer ${API_KEY}" \
       -H "Content-Type: application/json" \
       --data-raw "${data}" \
       "$@" \
       "${GATEWAY_URL}${path}"
}

echo "→ ${GATEWAY_URL}"

# 1. Unauthenticated /v1/coding/review must be rejected
status=$(http_status -X POST \
    -H "Content-Type: application/json" \
    --data-raw '{"task":"review","instructions":"check"}' \
    "${GATEWAY_URL}/v1/coding/review")
[[ "${status}" == "401" ]] || fail "/v1/coding/review without auth = ${status} (expected 401)"
ok "/v1/coding/review without auth = 401"

# 2. /v1/coding/review happy path — small synthetic diff
review_body=$(cat <<'JSON'
{
  "task": "review",
  "language": "python",
  "diff": "--- a/app.py\n+++ b/app.py\n@@\n-def foo():\n-    return 1\n+def foo():\n+    return 2\n",
  "instructions": "Skim this tiny diff and report nothing unusual."
}
JSON
)
body=$(post_json /v1/coding/review "${review_body}")
code=$(echo "${body}" | jq -r '.error.code // empty')
if [[ -n "${code}" ]]; then
  echo "note: /v1/coding/review returned error envelope: ${code}"
  echo "${body}"
else
  echo "${body}" | jq -e '.summary and .findings and .final_recommendation' >/dev/null \
    || fail "/v1/coding/review body missing required fields: ${body}"
  ok "/v1/coding/review = 200 with structured body"
fi

# 3. /v1/coding/architecture happy path
arch_body=$(cat <<'JSON'
{
  "task": "architecture",
  "instructions": "What would you change about a monolithic Flask app that handles auth, billing, and email in one module?"
}
JSON
)
body=$(post_json /v1/coding/architecture "${arch_body}")
code=$(echo "${body}" | jq -r '.error.code // empty')
if [[ -n "${code}" ]]; then
  echo "note: /v1/coding/architecture returned error envelope: ${code}"
else
  echo "${body}" | jq -e '.summary and .final_recommendation' >/dev/null \
    || fail "/v1/coding/architecture body missing required fields: ${body}"
  ok "/v1/coding/architecture = 200"
fi

# 4. /v1/coding/refactor-plan happy path
refactor_body=$(cat <<'JSON'
{
  "task": "refactor-plan",
  "instructions": "Extract the billing module from the monolith."
}
JSON
)
body=$(post_json /v1/coding/refactor-plan "${refactor_body}")
code=$(echo "${body}" | jq -r '.error.code // empty')
if [[ -n "${code}" ]]; then
  echo "note: /v1/coding/refactor-plan returned error envelope: ${code}"
else
  echo "${body}" | jq -e '.summary and .final_recommendation' >/dev/null \
    || fail "/v1/coding/refactor-plan body missing required fields: ${body}"
  ok "/v1/coding/refactor-plan = 200"
fi

# 5. /v1/coding/security-review happy path
security_body=$(cat <<'JSON'
{
  "task": "security-review",
  "instructions": "Look for OWASP top-10 concerns in a generic Python web app."
}
JSON
)
body=$(post_json /v1/coding/security-review "${security_body}")
code=$(echo "${body}" | jq -r '.error.code // empty')
if [[ -n "${code}" ]]; then
  echo "note: /v1/coding/security-review returned error envelope: ${code}"
else
  echo "${body}" | jq -e '.summary and .final_recommendation' >/dev/null \
    || fail "/v1/coding/security-review body missing required fields: ${body}"
  ok "/v1/coding/security-review = 200"
fi

# 6. Task / route mismatch
status=$(http_status -X POST \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    --data-raw '{"task":"architecture","instructions":"x"}' \
    "${GATEWAY_URL}/v1/coding/review")
[[ "${status}" == "422" ]] || fail "task=architecture on /review = ${status} (expected 422)"
ok "task=architecture on /review = 422"

echo "OK — coding intelligence surface responded."
