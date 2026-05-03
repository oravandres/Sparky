#!/usr/bin/env bash
# Download the Nemotron 3 Super reasoning parser plugin — PLAN §13 (Phase 4).
# Both vLLM and TensorRT-LLM require this file. NVIDIA's deployment guide:
#   https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html
#
# Stores the file under /opt/sparky/config/nemotron/ where
# docker-compose.nemotron.yml mounts it read-only into the container.
#
# Usage:
#   ./scripts/download-nemotron-parser.sh
#   SPARKY_NEMOTRON_PARSER_DIR=/tmp/parser ./scripts/download-nemotron-parser.sh
#
# This is one-time setup. Re-run when NVIDIA pushes a new parser revision
# (track the upstream commit in docs/operations.md).

set -euo pipefail

PARSER_URL="https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/raw/main/super_v3_reasoning_parser.py"
PARSER_DIR="${SPARKY_NEMOTRON_PARSER_DIR:-/opt/sparky/config/nemotron}"
PARSER_PATH="${PARSER_DIR}/super_v3_reasoning_parser.py"

if [[ ! -d "${PARSER_DIR}" ]]; then
  echo "error: ${PARSER_DIR} does not exist." >&2
  echo "Run playbooks/10-base-os.yml + playbooks/20-storage.yml first," >&2
  echo "or set SPARKY_NEMOTRON_PARSER_DIR to a writable directory." >&2
  exit 1
fi

echo "→ downloading ${PARSER_URL}"
echo "  destination: ${PARSER_PATH}"

# Use a tmp file so a half-failed download cannot leave a corrupted parser
# in place. curl --fail makes 4xx/5xx exit non-zero. The model repo is
# gated on Hugging Face — NVIDIA's deployment guide downloads the parser
# without auth, suggesting individual files are public, but pass HF_TOKEN
# when set so the script also works on operators who saw 401/404 once.
tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT

curl_args=(
  --silent --show-error --fail --location
  --max-time 60
  --output "${tmp}"
)
if [[ -n "${HF_TOKEN:-}" ]]; then
  curl_args+=(-H "Authorization: Bearer ${HF_TOKEN}")
fi

curl "${curl_args[@]}" "${PARSER_URL}"

# Sanity check — the parser is a small Python file, not a JSON 401 page.
# Look for the canonical class name. Fail loudly if we got HTML/JSON.
if ! grep -q 'super_v3' "${tmp}"; then
  echo "error: downloaded file does not look like the Nemotron reasoning parser." >&2
  echo "First line: $(head -n 1 "${tmp}")" >&2
  exit 1
fi

install -m 0644 "${tmp}" "${PARSER_PATH}"
echo "ok: ${PARSER_PATH} ($(wc -c < "${PARSER_PATH}") bytes)"
