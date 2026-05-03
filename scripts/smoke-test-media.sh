#!/usr/bin/env bash
# Smoke-test /v1/media/{image,video}/jobs and the shared job-control
# endpoints against a running gateway — see PLAN.md §16, §18, §21.
#
# Verifies:
#   1. unauth POST /v1/media/image/jobs                 returns 401
#   2. POST /v1/media/image/jobs (approved model)       returns 202 + {job_id, type, status}
#   3. POST /v1/media/video/jobs (envelope-aligned)     returns 202 + {job_id, type, status}
#   4. POST /v1/media/image/jobs with text model        returns 422
#   5. POST /v1/media/video/jobs with bad max_frames    returns 422
#   6. GET  /v1/jobs/{job_id}                           returns 200 with status=queued
#   7. POST /v1/jobs/{job_id}/cancel                    returns 200 with status=cancelled
#   8. POST /v1/jobs/{job_id}/cancel (idempotent)       returns 200 with status=cancelled
#   9. GET  /v1/jobs/<unknown-uuid>                     returns 404
#
# The smoke test never requires ComfyUI to be running because the gateway
# only enqueues — actual job execution is the worker's job (PLAN §7.2).
# What this *does* exercise is the gateway's contract and the file-backed
# job ledger from PLAN §18.
#
# Requires `jq` in PATH.
#
# Usage:
#   SPARKY_API_KEY=... ./scripts/smoke-test-media.sh
#   SPARKY_GATEWAY_URL=http://sparky.mimi.local:8080 ./scripts/smoke-test-media.sh

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

# 1. Unauthenticated /v1/media/image/jobs must be rejected
status=$(http_status -X POST \
    -H "Content-Type: application/json" \
    --data-raw '{"model":"flux2-dev","prompt":"x"}' \
    "${GATEWAY_URL}/v1/media/image/jobs")
[[ "${status}" == "401" ]] || fail "/v1/media/image/jobs without auth = ${status} (expected 401)"
ok "/v1/media/image/jobs without auth = 401"

# 2. /v1/media/image/jobs happy path
image_body='{"model":"flux2-dev","prompt":"a small cat in a sunlit kitchen","width":1024,"height":1024,"steps":30}'
post_json_authed /v1/media/image/jobs "${image_body}"
[[ "${_status}" == "202" ]] || fail "/v1/media/image/jobs = ${_status} (expected 202): ${_body}"
echo "${_body}" \
  | jq -e '.job_id and (.type == "image") and (.status == "queued")' >/dev/null \
  || fail "image job body missing required fields: ${_body}"
IMAGE_JOB_ID=$(echo "${_body}" | jq -r '.job_id')
ok "/v1/media/image/jobs = 202 (job_id=${IMAGE_JOB_ID})"

# 3. /v1/media/video/jobs happy path
# duration 5s × 24 fps = 120 frames; 1280×720×120 = 110_592_000 pixel-frames
video_body='{"model":"ltx-2","prompt":"a serene lake at dawn","duration_seconds":5,"fps":24,"width":1280,"height":720,"max_frames":120,"max_pixel_frames":110592000}'
post_json_authed /v1/media/video/jobs "${video_body}"
[[ "${_status}" == "202" ]] || fail "/v1/media/video/jobs = ${_status} (expected 202): ${_body}"
echo "${_body}" \
  | jq -e '.job_id and (.type == "video") and (.status == "queued")' >/dev/null \
  || fail "video job body missing required fields: ${_body}"
VIDEO_JOB_ID=$(echo "${_body}" | jq -r '.job_id')
ok "/v1/media/video/jobs = 202 (job_id=${VIDEO_JOB_ID})"

# 4. Image route rejects a text model with 422
post_json_authed /v1/media/image/jobs \
    '{"model":"nemotron-3-super-120b-a12b-nvfp4","prompt":"x"}'
[[ "${_status}" == "422" ]] \
  || fail "image route with text model = ${_status} (expected 422): ${_body}"
ok "image route with text model = 422"

# 5. Video route rejects a max_frames mismatch (Phase 1 envelope)
bad_video='{"model":"ltx-2","prompt":"x","duration_seconds":5,"fps":24,"width":1280,"height":720,"max_frames":119,"max_pixel_frames":110592000}'
post_json_authed /v1/media/video/jobs "${bad_video}"
[[ "${_status}" == "422" ]] \
  || fail "video route with max_frames mismatch = ${_status} (expected 422): ${_body}"
ok "video route with max_frames mismatch = 422"

# 6. GET /v1/jobs/{job_id} returns the queued record
get_authed "/v1/jobs/${IMAGE_JOB_ID}"
[[ "${_status}" == "200" ]] \
  || fail "GET /v1/jobs/${IMAGE_JOB_ID} = ${_status} (expected 200): ${_body}"
echo "${_body}" \
  | jq -e --arg id "${IMAGE_JOB_ID}" '(.job_id == $id) and (.status == "queued")' \
       >/dev/null \
  || fail "GET /v1/jobs/${IMAGE_JOB_ID} body unexpected: ${_body}"
ok "GET /v1/jobs/{image_job_id} = 200 status=queued"

# 7. POST /v1/jobs/{job_id}/cancel transitions to cancelled
post_json_authed "/v1/jobs/${IMAGE_JOB_ID}/cancel" ''
[[ "${_status}" == "200" ]] \
  || fail "cancel = ${_status} (expected 200): ${_body}"
echo "${_body}" \
  | jq -e '.status == "cancelled"' >/dev/null \
  || fail "cancel response not cancelled: ${_body}"
ok "POST /v1/jobs/{image_job_id}/cancel = 200 status=cancelled"

# 8. cancel is idempotent against an already-cancelled job
post_json_authed "/v1/jobs/${IMAGE_JOB_ID}/cancel" ''
[[ "${_status}" == "200" ]] \
  || fail "cancel idempotent = ${_status} (expected 200): ${_body}"
echo "${_body}" \
  | jq -e '.status == "cancelled"' >/dev/null \
  || fail "second cancel not idempotent: ${_body}"
ok "POST /v1/jobs/{image_job_id}/cancel (idempotent) = 200"

# 9. GET /v1/jobs/<unknown> = 404
get_authed "/v1/jobs/22222222-2222-4222-8222-222222222222"
[[ "${_status}" == "404" ]] \
  || fail "GET unknown job_id = ${_status} (expected 404): ${_body}"
ok "GET /v1/jobs/<unknown> = 404"

echo "OK — media + job control surface is end-to-end healthy."
