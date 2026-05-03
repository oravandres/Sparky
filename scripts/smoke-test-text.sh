#!/usr/bin/env bash
# Smoke-test the Nemotron text path through the gateway — PLAN §13.1, §21.
#
# Verifies:
#   1. unauth POST /v1/chat/completions                 returns 401
#   2. POST with the approved Nemotron model id         returns 200 with a non-empty assistant message
#   3. POST with an unapproved model id                 returns 422 with envelope.error="unapproved_model"
#   4. POST with a streaming flag                       returns 422 (gateway forbids streaming)
#
# Requires `jq` in PATH and a running Nemotron vLLM behind the gateway.
# This is an end-to-end test — the runtime must actually be loaded; on a
# cold cache it can take 20+ minutes for vLLM to come up. Use
# `docker compose -f docker/compose/docker-compose.nemotron.yml logs -f`
# to watch model load.
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-text.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-text.sh
#   SPARKY_TEXT_MODEL=nemotron-3-super-120b-a12b-nvfp4 ./scripts/smoke-test-text.sh   # default

set -euo pipefail

GATEWAY_URL="${SPARKY_GATEWAY_URL:-http://127.0.0.1:8080}"
API_KEY="${SPARKY_API_KEY:-}"
MODEL_ID="${SPARKY_TEXT_MODEL:-nemotron-3-super-120b-a12b-nvfp4}"
PROMPT="${SPARKY_TEXT_PROMPT:-Reply with the single word READY and nothing else.}"

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

post_json_authed() {
  local data="$1"
  local tmp
  tmp=$(mktemp)
  _status=$(curl --silent --output "${tmp}" --max-time 120 \
       --write-out '%{http_code}' \
       -H "Authorization: Bearer ${API_KEY}" \
       -H "Content-Type: application/json" \
       --data-raw "${data}" \
       "${GATEWAY_URL}/v1/chat/completions")
  _body=$(cat "${tmp}")
  rm -f "${tmp}"
}

post_json_unauthed() {
  local data="$1"
  curl --silent --output /dev/null --max-time 10 \
       --write-out '%{http_code}' \
       -H "Content-Type: application/json" \
       --data-raw "${data}" \
       "${GATEWAY_URL}/v1/chat/completions"
}

echo "→ ${GATEWAY_URL} (model=${MODEL_ID})"

# 1. Unauthenticated request must be rejected.
status=$(post_json_unauthed '{"model":"'"${MODEL_ID}"'","messages":[{"role":"user","content":"ping"}]}')
[[ "${status}" == "401" ]] || fail "unauth /v1/chat/completions returned ${status} (expected 401)"
ok "unauth /v1/chat/completions = 401"

# 2. Approved model — should get a real completion. This is the slow test.
post_json_authed '{
  "model":"'"${MODEL_ID}"'",
  "messages":[{"role":"user","content":"'"${PROMPT}"'"}],
  "max_tokens":32,
  "temperature":0
}'
[[ "${_status}" == "200" ]] || fail "/v1/chat/completions returned ${_status}: ${_body}"
content=$(echo "${_body}" | jq -r '.choices[0].message.content // empty')
[[ -n "${content}" ]] || fail "empty assistant content in response: ${_body}"
ok "/v1/chat/completions = 200 with content (${#content} chars)"

# 3. Unapproved model id must be rejected with envelope.
post_json_authed '{"model":"unknown-model","messages":[{"role":"user","content":"ping"}]}'
[[ "${_status}" == "422" ]] || fail "unapproved model returned ${_status} (expected 422)"
err=$(echo "${_body}" | jq -r '.error.code // empty')
[[ "${err}" == "unapproved_model" ]] || fail "unapproved model envelope.code = ${err} (expected unapproved_model)"
ok "unapproved model id = 422 with error.code=unapproved_model"

# 4. Streaming is forbidden by the gateway (PLAN §12 — bounded generation).
post_json_authed '{"model":"'"${MODEL_ID}"'","messages":[{"role":"user","content":"ping"}],"stream":true}'
[[ "${_status}" == "422" ]] || fail "stream=true returned ${_status} (expected 422)"
ok "stream=true = 422"

echo "OK — Nemotron text path is up."
