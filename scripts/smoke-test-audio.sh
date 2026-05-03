#!/usr/bin/env bash
# Smoke-test /v1/audio/{tts,asr}/jobs and the shared job-control endpoints
# against a running gateway — see PLAN.md §17, §18, §21.
#
# Verifies:
#   1. unauth POST /v1/audio/tts/jobs                  returns 401
#   2. POST /v1/audio/tts/jobs (approved model)        returns 202 + {job_id, type, status}
#   3. POST /v1/audio/asr/jobs (approved input_uri)    returns 202 + {job_id, type, status}
#   4. POST /v1/audio/tts/jobs with text model         returns 422
#   5. POST /v1/audio/asr/jobs with TTS model          returns 422
#   6. POST /v1/audio/asr/jobs with traversal URI      returns 422
#   7. POST /v1/audio/asr/jobs with non-file scheme    returns 422
#   8. GET  /v1/jobs/{job_id} for the TTS job          returns 200 with status=queued and type=tts
#   9. POST /v1/jobs/{job_id}/cancel for the ASR job   returns 200 with status=cancelled
#
# The smoke test never requires the audio service to be running because the
# gateway only enqueues — actual TTS/ASR work is the audio service's job
# (PLAN §4.1 sparky-audio on 127.0.0.1:9001). What this *does* exercise is
# the gateway's contract and the shared file-backed job ledger from PLAN §18.
#
# Requires `jq` in PATH.
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-audio.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-audio.sh

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

# Run an authenticated POST and set:
#   _status — the HTTP status code
#   _body   — the response body
post_json_authed() {
  local path="$1"
  local data="$2"
  local tmp
  tmp=$(mktemp)
  _status=$(curl --silent --output "${tmp}" --max-time 30 \
       --write-out '%{http_code}' \
       -H "Authorization: Bearer ${API_KEY}" \
       -H "Content-Type: application/json" \
       --data-raw "${data}" \
       "${GATEWAY_URL}${path}")
  _body=$(cat "${tmp}")
  rm -f "${tmp}"
}

# Run an authenticated GET.
get_authed() {
  local path="$1"
  local tmp
  tmp=$(mktemp)
  _status=$(curl --silent --output "${tmp}" --max-time 10 \
       --write-out '%{http_code}' \
       -H "Authorization: Bearer ${API_KEY}" \
       "${GATEWAY_URL}${path}")
  _body=$(cat "${tmp}")
  rm -f "${tmp}"
}

http_status() {
  curl --silent --output /dev/null --max-time 30 \
       --write-out '%{http_code}' \
       "$@"
}

echo "→ ${GATEWAY_URL}"

# 1. Unauthenticated /v1/audio/tts/jobs must be rejected
status=$(http_status -X POST \
    -H "Content-Type: application/json" \
    --data-raw '{"model":"qwen3-tts","text":"hi"}' \
    "${GATEWAY_URL}/v1/audio/tts/jobs")
[[ "${status}" == "401" ]] || fail "/v1/audio/tts/jobs without auth = ${status} (expected 401)"
ok "/v1/audio/tts/jobs without auth = 401"

# 2. /v1/audio/tts/jobs happy path
tts_body='{"model":"qwen3-tts","text":"hello world","language":"en","voice":"default","style":"calm"}'
post_json_authed /v1/audio/tts/jobs "${tts_body}"
[[ "${_status}" == "202" ]] || fail "/v1/audio/tts/jobs = ${_status} (expected 202): ${_body}"
echo "${_body}" \
  | jq -e '.job_id and (.type == "tts") and (.status == "queued")' >/dev/null \
  || fail "tts job body missing required fields: ${_body}"
TTS_JOB_ID=$(echo "${_body}" | jq -r '.job_id')
ok "/v1/audio/tts/jobs = 202 (job_id=${TTS_JOB_ID})"

# 3. /v1/audio/asr/jobs happy path
asr_body='{"model":"qwen3-asr","input_uri":"file:///data/outputs/audio/sample.wav","language":"auto"}'
post_json_authed /v1/audio/asr/jobs "${asr_body}"
[[ "${_status}" == "202" ]] || fail "/v1/audio/asr/jobs = ${_status} (expected 202): ${_body}"
echo "${_body}" \
  | jq -e '.job_id and (.type == "asr") and (.status == "queued")' >/dev/null \
  || fail "asr job body missing required fields: ${_body}"
ASR_JOB_ID=$(echo "${_body}" | jq -r '.job_id')
ok "/v1/audio/asr/jobs = 202 (job_id=${ASR_JOB_ID})"

# 4. TTS route rejects a text model with 422
post_json_authed /v1/audio/tts/jobs \
    '{"model":"nemotron-3-super-120b-a12b-nvfp4","text":"hi"}'
[[ "${_status}" == "422" ]] \
  || fail "tts route with text model = ${_status} (expected 422): ${_body}"
ok "tts route with text model = 422"

# 5. ASR route rejects a TTS model with 422
post_json_authed /v1/audio/asr/jobs \
    '{"model":"qwen3-tts","input_uri":"file:///data/outputs/audio/sample.wav"}'
[[ "${_status}" == "422" ]] \
  || fail "asr route with tts model = ${_status} (expected 422): ${_body}"
ok "asr route with tts model = 422"

# 6. ASR rejects path traversal in input_uri (PLAN §17 + §10)
post_json_authed /v1/audio/asr/jobs \
    '{"model":"qwen3-asr","input_uri":"file:///data/outputs/../etc/passwd"}'
[[ "${_status}" == "422" ]] \
  || fail "asr with traversal uri = ${_status} (expected 422): ${_body}"
ok "asr with .. traversal = 422"

# 7. ASR rejects non-file:// schemes
post_json_authed /v1/audio/asr/jobs \
    '{"model":"qwen3-asr","input_uri":"http://example.com/audio.wav"}'
[[ "${_status}" == "422" ]] \
  || fail "asr with http scheme = ${_status} (expected 422): ${_body}"
ok "asr with http scheme = 422"

# 8. GET /v1/jobs/{tts_job_id} returns the queued record
get_authed "/v1/jobs/${TTS_JOB_ID}"
[[ "${_status}" == "200" ]] \
  || fail "GET /v1/jobs/${TTS_JOB_ID} = ${_status} (expected 200): ${_body}"
echo "${_body}" \
  | jq -e --arg id "${TTS_JOB_ID}" \
       '(.job_id == $id) and (.status == "queued") and (.type == "tts")' \
       >/dev/null \
  || fail "GET /v1/jobs/${TTS_JOB_ID} body unexpected: ${_body}"
ok "GET /v1/jobs/{tts_job_id} = 200 status=queued type=tts"

# 9. POST /v1/jobs/{asr_job_id}/cancel transitions to cancelled
post_json_authed "/v1/jobs/${ASR_JOB_ID}/cancel" ''
[[ "${_status}" == "200" ]] \
  || fail "cancel asr job = ${_status} (expected 200): ${_body}"
echo "${_body}" \
  | jq -e '(.status == "cancelled") and (.type == "asr")' >/dev/null \
  || fail "cancel response not cancelled: ${_body}"
ok "POST /v1/jobs/{asr_job_id}/cancel = 200 status=cancelled"

echo "OK — audio submission + shared job control surface is end-to-end healthy."
