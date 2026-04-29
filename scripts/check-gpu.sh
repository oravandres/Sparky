#!/usr/bin/env bash
# NVIDIA / Docker GPU visibility check — PLAN §11 Phase 2 validation.
#
# Usage:
#   ./scripts/check-gpu.sh
#   ./scripts/check-gpu.sh --host-only    # host nvidia-smi only (CI laptops without Docker GPU)
#   SPARKY_CUDA_IMAGE=nvidia/cuda:12.6.3-runtime-ubuntu22.04 ./scripts/check-gpu.sh
#
# Override SPARKY_CUDA_IMAGE if the default multi-arch tag fails on DGX Spark;
# follow NVIDIA guidance for ARM64 CUDA images when needed.
#
# Environment:
#   SPARKY_GPU_CHECK_HOST_ONLY=1  Same as --host-only (explicit escape hatch).

set -euo pipefail

readonly ME="${0##*/}"
CUDA_IMAGE="${SPARKY_CUDA_IMAGE:-nvidia/cuda:12.6.3-runtime-ubuntu22.04}"
HOST_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host-only)
      HOST_ONLY=1
      shift
      ;;
    -h | --help)
      sed -n '1,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "${ME}: unknown option: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -n "${SPARKY_GPU_CHECK_HOST_ONLY:-}" ]] && [[ "${SPARKY_GPU_CHECK_HOST_ONLY}" != "0" ]]; then
  HOST_ONLY=1
fi

echo "=== Sparky GPU check (${ME}) ==="

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[fail] nvidia-smi not found — install NVIDIA drivers first." >&2
  exit 1
fi

echo "--- Host nvidia-smi ---"
nvidia-smi

if [[ "${HOST_ONLY}" -eq 1 ]]; then
  echo "[warn] --host-only / SPARKY_GPU_CHECK_HOST_ONLY: skipping Docker GPU probe." >&2
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[fail] docker not found — install Docker + NVIDIA Container Toolkit, or run with --host-only if intentional." >&2
  exit 1
fi

echo "--- Docker GPU probe (${CUDA_IMAGE}) ---"
if docker run --rm --gpus all "${CUDA_IMAGE}" nvidia-smi; then
  echo "[ok] Container sees NVIDIA GPU(s)."
else
  echo "[fail] Docker GPU probe failed. Install NVIDIA Container Toolkit; on DGX Spark you may need a different SPARKY_CUDA_IMAGE." >&2
  exit 1
fi

echo "[ok] GPU check finished successfully."
