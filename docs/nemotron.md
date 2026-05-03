# Nemotron 3 Super (Phase 4)

> Implements PLAN §13 — premium text runtime for the Sparky appliance.
> Source of truth for the serve command + env vars:
> [NVIDIA Nemotron 3 Super — DGX Spark Deployment Guide](https://docs.nvidia.com/nemotron/nightly/usage-cookbook/Nemotron-3-Super/SparkDeploymentGuide/README.html).

## Approved model

| Field | Value |
|---|---|
| Model | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` |
| Registry id | `nemotron-3-super-120b-a12b-nvfp4` (`config/model-registry.yaml`) |
| Runtime | vLLM nightly (PLAN §13.1) |
| Image | `vllm/vllm-openai:cu130-nightly` |
| Bind | container `0.0.0.0:8000` → host `127.0.0.1:8000` |
| Tier | A — always hot, never evicted (PLAN §4.3) |
| Approx weights size | ~70 GB (NVFP4) |
| Max model len | 1,000,000 tokens |
| KV cache dtype | FP8 |

## First-time bring-up

Prerequisites: Phase 1+2 done — `/etc/sparky/sparky.env` exists with `HF_TOKEN`, `/data/cache/huggingface` exists, NVIDIA Container Toolkit validated (`/var/lib/sparky/nvidia-validation.json` present).

```bash
# 1. One-time: fetch the reasoning parser plugin to /opt/sparky/config/nemotron/.
./scripts/download-nemotron-parser.sh

# 2. Start vLLM. First boot pulls ~70 GB — expect 10-30 minutes on first run.
SPARKY_ENV_FILE=/etc/sparky/sparky.env ./scripts/start-nemotron-vllm.sh up -d

# 3. Watch the model load.
SPARKY_ENV_FILE=/etc/sparky/sparky.env ./scripts/start-nemotron-vllm.sh logs -f

# 4. Once vLLM logs "Application startup complete" and /health is 200, smoke
#    the chat path through the gateway:
SPARKY_API_KEY=... ./scripts/smoke-test-text.sh
```

## Why these flags

The serve command in `docker/compose/docker-compose.nemotron.yml` matches NVIDIA's DGX Spark deployment guide verbatim. Don't edit without rerunning the §22 / §23 benchmarks — single-GPU NVFP4 inference is sensitive to backend choice.

| Flag | Value | Rationale |
|---|---|---|
| `VLLM_NVFP4_GEMM_BACKEND` | `marlin` | Marlin GEMM for NVFP4 on DGX Spark; FlashInfer FP4 MoE is multi-GPU Blackwell only. |
| `VLLM_ALLOW_LONG_MAX_MODEL_LEN` | `1` | Required for `--max-model-len 1000000` on a single GPU. |
| `VLLM_FLASHINFER_ALLREDUCE_BACKEND` | `trtllm` | Fixes allreduce on single-GPU topology (vLLM PR #35793). |
| `VLLM_USE_FLASHINFER_MOE_FP4` | `0` | Disabled — Marlin handles FP4 MoE on Spark. |
| `--kv-cache-dtype fp8` | FP8 | Fits the 1M context window in 128 GiB unified memory. |
| `--max-num-seqs 4` | 4 | Conservative concurrency for single-GPU memory headroom. |
| `--moe-backend marlin` | Marlin | Single-GPU NVFP4 MoE backend. |
| `--mamba_ssm_cache_dtype float32` | FP32 | Mamba-2 SSM cache (distinct from KV cache). |
| `--quantization fp4` | FP4 | NVFP4 quantised checkpoint. |
| `--speculative_config` | MTP, 3 draft tokens, Triton MoE | Lightweight speculative decoding via the baked-in MTP head. |
| `--reasoning-parser super_v3` | NVIDIA parser plugin | Required for tool-call / reasoning extraction. |
| `--tool-call-parser qwen3_coder` | Qwen3 Coder | Tool-call format the parser emits. |

## Gateway integration

The gateway already proxies `POST /v1/chat/completions` to the URL in `nemotron_vllm_url` (default `http://127.0.0.1:8000`, see `services/sparky-gateway/src/sparky_gateway/config.py`). Once vLLM serves the model with `--served-model-name nemotron-3-super-120b-a12b-nvfp4`, requests arriving at the gateway with `model: "nemotron-3-super-120b-a12b-nvfp4"` round-trip cleanly.

`smoke-test-text.sh` exercises four cases:
1. Unauth POST → 401
2. Authed POST with the approved model id → 200 with non-empty content
3. Authed POST with an unapproved model id → 422 / `error.code=unapproved_model`
4. Authed POST with `stream=true` → 422 (the gateway forbids streaming per PLAN §12)

## Operational notes

- **Always-hot.** Per PLAN §4.3, Nemotron is Tier A and never evicted. Don't `compose down` to make room for a media model — the eviction policy assumes Nemotron stays loaded.
- **Restart cost.** A warm restart (weights already downloaded) takes ~2–5 minutes for vLLM to reload the model. A cold restart (cache cleared) re-downloads ~70 GB.
- **TRT-LLM is opt-in.** PLAN §13.2 keeps vLLM as the default until TRT-LLM has run two consecutive weeks without crashes / OOMs / quality regressions. `scripts/start-nemotron-trtllm.sh` is a documented stub that exits non-zero with the promotion rule.
- **Parser refreshes.** When NVIDIA pushes a new `super_v3_reasoning_parser.py`, rerun `scripts/download-nemotron-parser.sh` and `compose restart` the service. Track the upstream commit hash in `docs/operations.md` "Recorded values".

## Benchmarks (PLAN §23)

Once the runtime is stable, `scripts/benchmark-nemotron.sh` (lands with the §23 benchmarking PR) records:

- Time to first token at the approved `--max-num-seqs 4`.
- Tokens/sec at 8k-, 64k-, 256k-token contexts.
- Peak unified memory utilisation at 1M context.
- Cold-restart vs warm-restart load times.

Results land in `docs/benchmark-results.md`.
