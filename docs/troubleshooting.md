# Troubleshooting

> Status: stub. Populated as real issues are encountered. Per
> [`PLAN.md`](../PLAN.md) §26 ("Agent notes"), every blocker should be
> recorded here so subsequent operators don't re-derive the workaround.

Format for each entry:

```text
### Symptom (one line)

Affected: <service / phase / model>
Date observed: YYYY-MM-DD

Root cause: ...
Workaround: ...
Permanent fix: PR #... or "pending"
References: PLAN section / external links
```

## Open blockers

_None yet._

## Known patterns to watch for

These haven't blocked us yet but operators should recognise them. Promote
to "Open blockers" with date + workaround when seen.

### Nemotron vLLM container OOM during model load

Affected: Phase 4 / `docker-compose.nemotron.yml`

Root cause: cold cache + 1M `--max-model-len` + concurrent system load can
push unified memory past the 90% utilisation limit while vLLM is still
constructing the KV cache.

Workaround: stop other GPU consumers (ComfyUI, audio service); reduce
`--max-num-seqs` from 4 to 2 in the compose unit; increase swap if the host
swap is saturated. The serve command in this repo matches NVIDIA's DGX
Spark guide — straying invalidates the §13.1 benchmarks.

### Nemotron `/health` not 200 after 30 minutes

Affected: Phase 4 / `docker-compose.nemotron.yml` healthcheck

Root cause: first-time download of ~70 GB NVFP4 weights from the gated HF
repo; HF rate-limit or transient network errors stretch the pull. The
compose `start_period: 30m` was sized for the steady state — fresh
appliances on slow links may need longer.

Workaround: tail logs with `./scripts/start-nemotron-vllm.sh logs -f` to
confirm whether the model is still loading. If the container has reached
"Application startup complete" but the healthcheck is still failing, check
that nothing in the loopback path was firewalled.

### `super_v3_reasoning_parser.py` 404

Affected: `scripts/download-nemotron-parser.sh`

Root cause: HF return 404 if the model repo is gated and the request is
unauthenticated. The parser file lives at the same gated repo as the
weights, so accessing it requires the same `HF_TOKEN`.

Workaround: pass the token explicitly:
`HF_TOKEN=... curl -H "Authorization: Bearer $HF_TOKEN" -o /opt/sparky/config/nemotron/super_v3_reasoning_parser.py 'https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4/raw/main/super_v3_reasoning_parser.py'`.
The download script will be updated to do this automatically once we
confirm the gating model on the parser file.

## Resolved
