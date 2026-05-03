#!/usr/bin/env bash
# Stub for the TensorRT-LLM optimisation track — PLAN §13.2 (Phase 14).
#
# Per the promotion rule (PLAN §13.2): vLLM remains the default runtime
# until TRT-LLM has run two consecutive weeks without crashes, OOMs, or
# quality regressions. The TRT-LLM compose unit + serve command land in
# a separate PR after vLLM is stable.
#
# This stub exists so PLAN §7.2 stays accurate: the file is referenced
# from the target on-disk layout. Keeping it as a documented placeholder
# beats a "file not found" surprise.

set -euo pipefail

cat >&2 <<'EOF'
TensorRT-LLM serving is not yet enabled.

PLAN §13.2 promotion rule:
  - vLLM remains the default until TRT-LLM has run two consecutive weeks
    without crashes, OOMs, or quality regressions.
  - TRT-LLM becomes default only via an explicit PR that flips
    `runtime: vllm` -> `runtime: trtllm` in config/model-registry.yaml.

NVIDIA's TRT-LLM serve command + extra-llm-api-config.yml for DGX Spark are
documented at:
  https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html#tensorrt-llm

When the optimisation track lands:
  - docker/compose/docker-compose.nemotron-trtllm.yml
  - config/nemotron/extra-llm-api-config.yml
  - benchmark results in docs/benchmark-results.md (PLAN §23)

Until then, stick with: ./scripts/start-nemotron-vllm.sh up -d
EOF

exit 64
