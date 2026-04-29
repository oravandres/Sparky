#!/usr/bin/env bash
# NVIDIA / Docker GPU visibility check — PLAN §11 Phase 2 validation.
#
# Usage:
#   ./scripts/check-gpu.sh
#   SPARKY_CUDA_IMAGE=nvidia/cuda:12.6.3-runtime-ubuntu22.04 ./scripts/check-gpu.sh
#
# Override SPARKY_CUDA_IMAGE if the default multi-arch tag fails on DGX Spark;
# follow NVIDIA guidance for ARM64 CUDA images when needed.

set -euo pipefail

readonly ME="${0##*/}"
CUDA_IMAGE="${SPARKY_CUDA_IMAGE:-nvidia/cuda:12.6.3-runtime-ubuntu22.04}"

echo "=== Sparky GPU check (${ME}) ==="

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "[fail] nvidia-smi not found — install NVIDIA drivers first." >&2
  exit 1
fi

echo "--- Host nvidia-smi ---"
nvidia-smi

if ! command -v docker >/dev/null 2>&1; then
  echo "[warn] docker not found — skipping container CUDA probe (install Docker + NVIDIA Container Toolkit)." >&2
  exit 0
fi

echo "--- Docker GPU probe (${CUDA_IMAGE}) ---"
if docker run --rm --gpus all "${CUDA_IMAGE}" nvidia-smi; then
  echo "[ok] Container sees NVIDIA GPU(s)."
else
  echo "[fail] Docker GPU probe failed. Install NVIDIA Container Toolkit; on DGX Spark you may need a different SPARKY_CUDA_IMAGE." >&2
  exit 1
fi

echo "[ok] GPU check finished successfully."
