
# Sparky PLAN.md — DGX Spark Main Intelligence Machine

> **Repository:** `Sparky`  
> **Machine:** NVIDIA DGX Spark, GB10 Grace Blackwell, ARM64, 128 GB unified memory  
> **Platform architecture:** MiMi K3s control plane + Darkbase RTX 5090 fast worker + Sparky DGX Spark main intelligence  
> **Purpose:** Turn Sparky into the premium local intelligence appliance for high-quality reasoning, agentic RAG synthesis, coding review, and premium media generation.  
> **Status:** Ready for implementation by agent  
> **License:** MIT (matches MiMi / DarkBase)  
> **Last updated:** 2026-04-28  

---

## 0. Mission

Sparky is the **main intelligence machine** of the local AI platform.

It must provide high-quality local AI capabilities through stable internal APIs:

- premium reasoning
- premium assistant answers
- premium agentic RAG planning, verification, and synthesis
- deep coding review and architecture analysis
- premium image generation
- premium video generation
- premium text-to-speech
- premium speech recognition

Sparky is **not** the control plane.

MiMi owns orchestration, routing, storage, queues, monitoring, and GitOps.  
Darkbase RTX 5090 owns fast daily assistant work, embeddings, reranking, and fast RAG drafts.  
Sparky owns the highest-quality local reasoning and generation.

---

## 1. Target Architecture

```text
User / MaestroUI / CLI / API
          |
          v
MiMi K3s Cluster
- Maestro
- MaestroUI
- AI Router
- RAG ingestion
- Qdrant
- Postgres
- Job queue
- Monitoring
- GitOps
          |
          +-----------------------------+
          |                             |
          v                             v
Darkbase RTX 5090                Sparky DGX Spark
Fast daily worker                Main intelligence machine
- Qwen3.6-35B-A3B               - Nemotron 3 Super NVFP4
- Qwen3 Embedding/Reranker      - Agentic RAG reasoning
- fast RAG drafts               - premium synthesis
- quick coding help             - deep coding review
                                 - image/video/audio generation
```

### 1.1 Sparky responsibilities

Sparky must provide:

```text
Premium text:
- NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4

Agentic RAG intelligence:
- planning
- query decomposition
- tool-selection recommendations
- evidence evaluation
- contradiction detection
- final synthesis
- citation-aware response drafting

Coding intelligence:
- architecture review
- deep code review
- security review
- refactor planning
- large-repository reasoning

Image generation:
- FLUX.2
- Qwen-Image latest
- HunyuanImage-3.0 / Instruct

Video generation:
- LTX-2
- Wan 2.2
- HunyuanVideo-1.5

Audio and speech:
- Qwen3-TTS
- VoxCPM2
- Qwen3-ASR
```

### 1.2 Sparky non-responsibilities

Do not move these responsibilities to Sparky:

```text
- Maestro orchestration
- MaestroUI
- AI Router global policy
- Qdrant primary vector database
- Postgres primary metadata database
- RAG ingestion ownership
- GitOps controllers
- cluster-wide monitoring ownership
- backup controller
- general Pi/K3s workloads
- routine daily assistant traffic
- embeddings and reranking by default
```

Sparky may expose metrics and logs to MiMi, but MiMi owns monitoring.

---

## 2. Non-Negotiable Design Rules

### 2.1 Sparky is an AI appliance, not a normal worker

Sparky should primarily run host-level AI services through:

```text
systemd + Docker / Docker Compose
```

Kubernetes join is allowed only for visibility, observability, or future controlled scheduling.

If Sparky joins MiMi K3s, it must be protected with labels and taints immediately.

Recommended labels:

```text
node-role.mimi.local/sparky=true
hardware.nvidia.com/dgx-spark=true
workload.mimi.local/premium-ai=true
kubernetes.io/arch=arm64
```

Recommended taint:

```text
workload.mimi.local/premium-ai=true:NoSchedule
```

Default implementation target:

```text
Sparky exposes stable authenticated APIs.
MiMi consumes Sparky as an external premium AI endpoint.
```

### 2.2 Latest-and-best-only model rule

Install only the approved premium model set.

Do not install older fallback models.

Explicitly excluded:

```text
- GPT-OSS-120B class models
- DeepSeek-V3.2-NVFP4
- FLUX.1
- FLUX.1-dev
- FLUX.1-Kontext
- SDXL
- Stable Diffusion 3.x
- Whisper / faster-whisper as default ASR
- Kokoro
- Fish Speech
- CosyVoice
- random Ollama models
- generic small fallback models
```

If an approved model cannot run, the implementation must fail clearly and document the blocker.

Do not silently substitute older or lower-quality models.

### 2.3 API-first rule

Every Sparky capability must be callable by other services through a stable API.

Minimum consumers:

```text
- Maestro
- AI Router
- MaestroUI
- Darkbase services
- future coding/review agents
- future media generation agents
```

Raw model runtimes may run locally, but external services should call the Sparky Gateway, not direct runtime ports.

---

## 3. Approved Model Matrix

Every entry below must be reflected exactly in `config/model-registry.yaml` (§7.3). HF repo IDs are pinned — the agent must not substitute "latest" for a different revision without updating this table.

| Capability | Approved model | HF / source repo | Runtime target | Approx size on disk | Priority |
|---|---|---|---|---:|---|
| Premium text / reasoning | NVIDIA Nemotron 3 Super 120B A12B NVFP4 | `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4` | vLLM nightly first, TensorRT-LLM second | ~70 GB | P0 |
| Image | FLUX.2 dev | `black-forest-labs/FLUX.2-dev` | ComfyUI workflow | ~24 GB | P1 |
| Image | FLUX.2 klein (open license fallback for FLUX.2-dev consumers when license matters) | `black-forest-labs/FLUX.2-klein` | ComfyUI workflow | ~24 GB | P1 |
| Image | Qwen-Image (latest pinned release at install time) | `Qwen/Qwen-Image` | ComfyUI workflow | ~20 GB | P1 |
| Image | HunyuanImage-3.0 Instruct | `tencent/HunyuanImage-3.0-Instruct` | ComfyUI or model-specific runtime | ~160 GB (80B MoE) | P1 |
| Video | LTX-2 | `Lightricks/LTX-Video-2` | ComfyUI workflow | ~30 GB | P1 |
| Video | Wan 2.2 | `Wan-AI/Wan2.2` | ComfyUI workflow | ~30 GB | P1 |
| Video | HunyuanVideo-1.5 | `tencent/HunyuanVideo-1.5` | ComfyUI or model-specific runtime | ~50 GB | P1 |
| TTS | Qwen3-TTS | `Qwen/Qwen3-TTS` | model-specific API | ~10 GB | P2 |
| TTS | VoxCPM2 | `OpenBMB/VoxCPM2` | model-specific API | ~8 GB | P2 |
| ASR | Qwen3-ASR | `Qwen/Qwen3-ASR` | model-specific API | ~8 GB | P2 |

> **Storage budget:** the full approved set is approximately **400–450 GB** of weights, before runtime caches (`/data/cache/*`). Preflight (§9) must verify ≥ 600 GB free on the data mount before starting downloads. If the device is smaller, install in priority order (P0 → P1 → P2) and document what was skipped.

> **Pin-at-install rule:** "latest" is resolved at first install and recorded in `config/model-registry.yaml` as a commit SHA or revision tag. Subsequent updates are explicit PRs to the registry, never silent.

> **Reference docs the agent must read before Phase 4:**
> - https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/
> - https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
> - https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/nemotron-3-super-120b-a12b

---

## 4. Service Topology

### 4.1 Services on Sparky

| Service | Purpose | Bind | Port |
|---|---|---|---:|
| `sparky-gateway` | Authenticated internal API gateway | `0.0.0.0` internal LAN only | `8080` |
| `sparky-nemotron-vllm` | Nemotron OpenAI-compatible runtime | `127.0.0.1` | `8000` |
| `sparky-nemotron-trtllm` | Future optimized runtime | `127.0.0.1` | `8001` |
| `comfyui` | Image/video workflow runtime | `127.0.0.1` by default | `8188` |
| `sparky-audio` | TTS/ASR service | `127.0.0.1` | `9001` |
| `sparky-worker` | Local async media/audio job worker | local | n/a |
| `node-exporter` | host metrics | internal LAN | `9100` |
| `gpu-exporter` | NVIDIA metrics, if supported | internal LAN | `9400` |

### 4.2 Network names

Preferred internal name:

```text
sparky.mimi.local
```

Fallback:

```text
sparky.local
```

The implementation must keep hostname/IP configurable.

### 4.3 Model co-residency and eviction policy

Sparky has **128 GB unified memory shared between CPU and GPU**. The full approved model set cannot be hot-resident at the same time. Order-of-magnitude footprints when loaded:

```text
Nemotron 3 Super 120B A12B NVFP4   ~ 60–70 GB
HunyuanImage-3.0 (80B MoE)         ~ 40–60 GB
HunyuanVideo-1.5                   ~ 30–40 GB
LTX-2 / Wan 2.2                    ~ 20–30 GB each
FLUX.2 dev/klein                   ~ 20–25 GB
Qwen-Image                         ~ 15–20 GB
Qwen3-TTS / VoxCPM2 / Qwen3-ASR    ~ 2–6 GB each
```

The gateway and worker MUST enforce this policy:

1. **Tier A — always hot:** the premium text runtime (Nemotron via vLLM) is `restart: always` and never evicted. It is the assistant's reasoning core.
2. **Tier B — single-slot media:** at most **one** image/video model is resident at a time. Switching models means: drain in-flight ComfyUI jobs, unload current model, load requested model, mark ready. The gateway must serialize media job submissions during a switch.
3. **Tier C — small/cheap:** TTS and ASR models may co-reside with media, since their footprint is small. Prefer keeping ASR hot during interactive sessions.
4. **Idle eviction:** Tier B models that have been idle for `eviction_idle_minutes` (per `model-registry.yaml`, default 15 minutes) are unloaded automatically.
5. **Headroom guard:** before loading any new model, verify free unified memory ≥ `vram_estimate_gb + 8 GB` headroom. If insufficient, evict the longest-idle Tier B/C model first and retry. If still insufficient, fail the request with a clear error — never partial-load.
6. **No over-subscription:** if a job arrives that needs both Nemotron and a 60 GB image model and headroom is too tight, prefer queuing the media job over evicting Nemotron.

This policy is implemented in `services/sparky-worker/` and surfaced via `/v1/models` (each entry includes `state: hot|cold|loading|evicting`).

---

## 5. Public Internal API Contract

All external consumers must call:

```text
http://sparky.mimi.local:8080
```

Use API key authentication:

```text
Authorization: Bearer <SPARKY_API_KEY>
```

### 5.1 Required base endpoints

```text
GET  /health
GET  /ready
GET  /v1/models
GET  /metrics
```

### 5.2 Premium text endpoints

```text
POST /v1/chat/completions
POST /v1/reasoning/analyze
POST /v1/reasoning/compare
```

`/v1/chat/completions` must be OpenAI-compatible where practical, so Maestro can call Sparky like a normal LLM provider.

#### 5.2.1 `POST /v1/reasoning/analyze`

Single-input deep analysis. Used by Maestro / AI Router for hard reasoning calls that need a structured output (not just chat text).

Request:

```json
{
  "task": "string",
  "context": "string",
  "criteria": ["string"],
  "output_style": "structured|prose|bulleted",
  "max_tokens": 2048
}
```

Response:

```json
{
  "summary": "string",
  "key_points": ["string"],
  "risks": ["string"],
  "assumptions": ["string"],
  "recommendation": "string",
  "confidence": "high|medium|low"
}
```

#### 5.2.2 `POST /v1/reasoning/compare`

Side-by-side comparison of N options against M criteria. Used for design choices, model choices, vendor comparisons, etc.

Request:

```json
{
  "question": "string",
  "options": [
    { "id": "string", "name": "string", "description": "string" }
  ],
  "criteria": [
    { "id": "string", "name": "string", "weight": 1.0 }
  ],
  "constraints": ["string"]
}
```

Response:

```json
{
  "scores": [
    {
      "option_id": "string",
      "criterion_id": "string",
      "score": 0,
      "rationale": "string"
    }
  ],
  "totals": [
    { "option_id": "string", "weighted_total": 0.0 }
  ],
  "recommendation": {
    "option_id": "string",
    "reasoning": "string",
    "caveats": ["string"]
  },
  "confidence": "high|medium|low"
}
```

### 5.3 Agentic RAG endpoints

```text
POST /v1/agentic-rag/plan
POST /v1/agentic-rag/evaluate-evidence
POST /v1/agentic-rag/verify
POST /v1/agentic-rag/synthesize
POST /v1/agentic-rag/finalize
```

### 5.4 Coding intelligence endpoints

```text
POST /v1/coding/review
POST /v1/coding/architecture
POST /v1/coding/refactor-plan
POST /v1/coding/security-review
```

### 5.5 Media endpoints

```text
POST /v1/media/image/jobs
POST /v1/media/video/jobs
```

### 5.6 Audio endpoints

```text
POST /v1/audio/tts/jobs
POST /v1/audio/asr/jobs
```

### 5.7 Job control (shared by media + audio)

A single set of endpoints serves all asynchronous job types (image, video, tts, asr). The job record (§18) carries a `type` field so consumers know what they got back.

```text
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
```

---

## 6. Agentic RAG Architecture

Agentic RAG must be first-class in Sparky.

Classic RAG:

```text
Question -> retrieve chunks -> generate answer
```

Agentic RAG:

```text
Question
  -> classify intent
  -> plan research
  -> decompose query
  -> select retrieval tools
  -> request retrieval from MiMi/Darkbase
  -> evaluate evidence
  -> request additional retrieval if needed
  -> synthesize answer
  -> verify claims
  -> return final answer with source IDs and confidence
```

### 6.1 Responsibility split

```text
MiMi:
- RAG orchestration
- document ingestion
- Qdrant
- Postgres metadata
- access control
- job queue
- source registry
- final UI integration

Darkbase RTX 5090:
- embeddings
- reranking
- fast query rewriting
- fast RAG drafts
- Qwen3.6 daily assistant

Sparky DGX Spark:
- agentic RAG planning
- retrieval strategy generation
- evidence quality evaluation
- contradiction analysis
- premium synthesis
- final answer verification
```

### 6.2 Agentic RAG flow

```text
1. User asks a knowledge-heavy question in MaestroUI.
2. MiMi AI Router decides that RAG is needed.
3. MiMi sends the question and available source list to Sparky:
   POST /v1/agentic-rag/plan

4. Sparky returns a retrieval plan:
   - intent
   - required facts
   - decomposed queries
   - preferred retrieval tools
   - filters
   - minimum evidence requirements

5. MiMi executes retrieval:
   - vector search in Qdrant
   - keyword search
   - metadata filters in Postgres
   - code/document search when needed

6. Darkbase reranks candidate chunks:
   - Qwen3-Reranker-8B
   - returns top evidence pack

7. MiMi sends evidence pack to Sparky:
   POST /v1/agentic-rag/evaluate-evidence

8. Sparky decides:
   - evidence is enough
   - evidence is incomplete
   - evidence is contradictory
   - more retrieval is needed

9. If more retrieval is needed:
   - Sparky returns follow-up retrieval requests
   - MiMi executes another retrieval loop

10. When evidence is sufficient:
    MiMi sends final evidence pack to:
    POST /v1/agentic-rag/synthesize

11. Sparky drafts the answer with source IDs attached.

12. MiMi or Sparky calls:
    POST /v1/agentic-rag/verify

13. Sparky returns:
    - supported claims
    - unsupported claims
    - contradictions
    - confidence
    - final answer readiness

14. MiMi returns the final answer to the user.
```

### 6.3 RAG plan request

```json
{
  "question": "string",
  "user_intent": "unknown|question|analysis|coding|research|summary",
  "available_sources": [
    {
      "source_id": "string",
      "source_type": "docs|code|pdf|audio|video|web|database",
      "description": "string",
      "metadata": {}
    }
  ],
  "constraints": {
    "require_citations": true,
    "max_retrieval_rounds": 3,
    "answer_style": "technical|executive|concise|detailed"
  }
}
```

### 6.4 RAG plan response

```json
{
  "intent": "string",
  "needs_rag": true,
  "required_facts": ["string"],
  "retrieval_rounds": [
    {
      "round": 1,
      "queries": ["string"],
      "tools": ["vector_search", "keyword_search", "metadata_search", "code_search"],
      "filters": {},
      "top_k": 30,
      "minimum_evidence": "string"
    }
  ],
  "reasoning_notes": "brief explanation for orchestrator only"
}
```

### 6.5 Evidence evaluation request

```json
{
  "question": "string",
  "evidence_chunks": [
    {
      "chunk_id": "string",
      "source_id": "string",
      "title": "string",
      "text": "string",
      "metadata": {}
    }
  ],
  "required_facts": ["string"]
}
```

### 6.6 Evidence evaluation response

```json
{
  "sufficient": true,
  "missing_facts": ["string"],
  "contradictions": [
    {
      "summary": "string",
      "chunk_ids": ["string"]
    }
  ],
  "recommended_followup_queries": ["string"],
  "confidence": "high|medium|low"
}
```

### 6.7 Synthesis request

```json
{
  "question": "string",
  "evidence_chunks": [
    {
      "chunk_id": "string",
      "source_id": "string",
      "title": "string",
      "text": "string",
      "metadata": {}
    }
  ],
  "answer_style": "technical|executive|concise|detailed",
  "require_citations": true,
  "max_tokens": 4096
}
```

### 6.8 Synthesis response

```json
{
  "answer": "string",
  "citations": [
    {
      "source_id": "string",
      "chunk_id": "string",
      "claim": "string"
    }
  ],
  "unsupported_claims": [],
  "confidence": "high|medium|low",
  "needs_more_retrieval": false
}
```

### 6.9 Verification request

```json
{
  "answer": "string",
  "evidence_chunks": [
    {
      "chunk_id": "string",
      "source_id": "string",
      "text": "string"
    }
  ]
}
```

### 6.10 Verification response

```json
{
  "supported_claims": ["string"],
  "unsupported_claims": ["string"],
  "contradictions": ["string"],
  "confidence": "high|medium|low",
  "final_answer_ready": true
}
```

### 6.11 Finalize request — `POST /v1/agentic-rag/finalize`

`finalize` is the optional last step that turns a verified draft into the user-facing answer. It strips unsupported claims (or flags them inline), formats citations, and produces the response shape that MaestroUI / AI Router consume directly. Synthesize + verify can be called separately by orchestrators that want manual control; finalize wraps both into a single call when MiMi just wants the final answer.

Request:

```json
{
  "question": "string",
  "draft_answer": "string",
  "evidence_chunks": [
    {
      "chunk_id": "string",
      "source_id": "string",
      "title": "string",
      "text": "string",
      "metadata": {}
    }
  ],
  "verification": {
    "supported_claims": ["string"],
    "unsupported_claims": ["string"],
    "contradictions": ["string"]
  },
  "format": "markdown|plaintext|json",
  "citation_style": "inline|footnote|none",
  "answer_style": "technical|executive|concise|detailed"
}
```

Response:

```json
{
  "final_answer": "string",
  "citations": [
    {
      "marker": "string",
      "source_id": "string",
      "chunk_id": "string",
      "claim": "string"
    }
  ],
  "removed_unsupported_claims": ["string"],
  "flagged_contradictions": ["string"],
  "confidence": "high|medium|low",
  "ready_for_user": true
}
```

### 6.12 Agentic RAG acceptance criteria

- [ ] Sparky can create a retrieval plan.
- [ ] Sparky can decompose a broad question into multiple retrieval queries.
- [ ] Sparky can evaluate whether retrieved evidence is enough.
- [ ] Sparky can request another retrieval round.
- [ ] Sparky can detect contradictions.
- [ ] Sparky can synthesize an answer from evidence.
- [ ] Sparky can verify its own answer against evidence.
- [ ] Source IDs and chunk IDs survive the full workflow.
- [ ] Unsupported claims are returned separately.
- [ ] MiMi can call the full flow through the Sparky Gateway.

---

## 7. Repository Structure

### 7.1 Existing repo state (do not duplicate)

The repo already contains:

```text
Sparky/
  ansible.cfg                 # roles_path = roles:../MiMi/roles
  inventory/
    hosts.yml                 # YAML inventory, keep as-is
    group_vars/                # gitignored, holds local secrets
  playbooks/
    join-k3s.yml               # optional K3s-agent join (see §2.1)
  roles/                       # currently empty
  PLAN.md
  README.md
  .gitignore
```

Reconciliation rule for the agent:

- **Keep the flat top-level Ansible layout** (`inventory/`, `playbooks/`, `roles/`, `ansible.cfg` at repo root). Do not move them under an `ansible/` subdirectory. The `ansible/` prefix in §7.2 is illustrative grouping only.
- **Keep `inventory/hosts.yml`** (YAML, not `hosts.ini`). New hosts/vars go in `inventory/group_vars/sparky.yml` (gitignored — track only `inventory/group_vars/sparky.yml.example`).
- **Keep `playbooks/join-k3s.yml`** as the optional K3s-agent join path (§2.1). Sparky's primary surface is host-level systemd + Docker Compose; K3s membership is allowed only for observability and must not change service ownership.
- **Add `services/`, `docker/`, `config/`, `scripts/`, `docs/`** as new top-level directories per §7.2.

### 7.2 Target on-disk layout

```text
Sparky/
  ansible.cfg
  PLAN.md
  README.md
  AGENTS.md                    # optional, mirrors other workspace repos
  .env.example
  .gitignore
  .pre-commit-config.yaml      # see §22 CI/quality gates
  .ansible-lint
  .yamllint

  inventory/
    hosts.yml
    group_vars/
      sparky.yml.example

  playbooks/
    join-k3s.yml                # existing, optional
    00-preflight.yml
    10-base-os.yml
    20-storage.yml
    30-container-runtime.yml
    40-nvidia-validation.yml
    50-sparky-gateway.yml
    60-nemotron.yml
    70-agentic-rag.yml
    80-coding.yml
    90-media.yml
    100-audio.yml
    110-monitoring.yml
    120-security.yml
    130-smoke-tests.yml

  roles/
    base/
    storage/
    containers/
    nvidia/
    gateway/
    nemotron/
    agentic_rag/
    coding/
    comfyui/
    audio/
    monitoring/
    security/

  docker/
    compose/
      docker-compose.yml
      docker-compose.gateway.yml
      docker-compose.nemotron.yml
      docker-compose.media.yml
      docker-compose.audio.yml
      docker-compose.monitoring.yml

  services/
    sparky-gateway/
      Dockerfile
      pyproject.toml
      src/
        sparky_gateway/
          main.py
          config.py
          auth.py
          health.py
          models.py
          proxy_text.py
          agentic_rag.py
          coding.py
          media.py
          audio.py
          jobs.py
          metrics.py
      tests/
        test_health.py
        test_auth.py
        test_agentic_rag.py
        test_coding.py

    sparky-worker/
      Dockerfile
      pyproject.toml
      src/
        sparky_worker/
          main.py
          job_store.py
          comfyui_client.py
          tts_client.py
          asr_client.py
      tests/
        test_job_store.py

  config/
    sparky.env.example
    model-registry.yaml          # see §7.3
    api-contract.yaml            # OpenAPI 3.1, see §7.4
    logging.yaml
    comfyui/
      workflows/

  scripts/
    preflight.sh
    check-gpu.sh
    download-models.sh
    start-gateway.sh
    start-nemotron-vllm.sh
    start-nemotron-trtllm.sh     # phase 2 stub until §13.2 lands
    start-media.sh
    start-audio.sh
    smoke-test-health.sh
    smoke-test-text.sh
    smoke-test-agentic-rag.sh
    smoke-test-coding.sh
    smoke-test-media.sh
    smoke-test-audio.sh
    benchmark-nemotron.sh

  docs/
    architecture.md
    api-contract.md
    agentic-rag.md
    operations.md
    troubleshooting.md
    benchmark-results.md

  .github/
    workflows/
      ci.yml                     # see §22
```

### 7.3 `config/model-registry.yaml` — required schema

This is the canonical mapping the gateway uses to resolve model IDs to runtimes. Implement it exactly:

```yaml
version: 1
models:
  - id: nemotron-3-super-120b-a12b-nvfp4
    family: text
    role: premium-text
    hf_repo: nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
    runtime: vllm
    runtime_url: http://127.0.0.1:8000
    weights_path: /data/models/text/nemotron-3-super-120b-a12b-nvfp4
    approx_size_gb: 70
    vram_estimate_gb: 70
    priority: P0
    active: true
    co_resident: false             # see §4.3
    eviction_idle_minutes: null    # always hot

  - id: flux2-dev
    family: image
    role: premium-image
    hf_repo: black-forest-labs/FLUX.2-dev
    runtime: comfyui
    runtime_url: http://127.0.0.1:8188
    weights_path: /data/models/image/flux2-dev
    approx_size_gb: 24
    priority: P1
    active: true
    co_resident: true              # one image model hot at a time
    eviction_idle_minutes: 15

  # ... one entry per model in §3
```

The gateway must:
- reject requests for `active: false` models with a clear error,
- never silently substitute a different model,
- expose this list (filtered to `active: true`) at `GET /v1/models`.

### 7.4 `config/sparky.env.example` — required keys

`.env` files are loaded by Compose. The agent must commit only the example, never a real `.env`.

```bash
# --- gateway ---
SPARKY_API_KEY=                    # required, see §10 "Secrets sourcing"
SPARKY_GATEWAY_BIND=0.0.0.0:8080
SPARKY_LOG_LEVEL=info
SPARKY_REQUEST_TIMEOUT_SECONDS=120

# --- runtimes ---
NEMOTRON_VLLM_URL=http://127.0.0.1:8000
NEMOTRON_TRTLLM_URL=http://127.0.0.1:8001
COMFYUI_URL=http://127.0.0.1:8188
AUDIO_SERVICE_URL=http://127.0.0.1:9001

# --- paths (see §8) ---
MODELS_DIR=/data/models
CACHE_DIR=/data/cache
OUTPUTS_DIR=/data/outputs
JOBS_DIR=/var/lib/sparky/jobs
LOGS_DIR=/var/log/sparky

# --- model downloads ---
HF_TOKEN=                          # required for some weights
NGC_API_KEY=                       # required for NVIDIA NGC pulls

# --- monitoring ---
ENABLE_GPU_EXPORTER=true
```

### 7.5 `config/api-contract.yaml`

OpenAPI 3.1 document covering every endpoint declared in §5. The agent must keep it in sync with FastAPI route definitions; CI lints both for drift (§22).

---

## 8. Host Paths

Create and use these paths:

```text
/opt/sparky
/opt/sparky/config
/opt/sparky/services

/data/models
/data/models/text
/data/models/image
/data/models/video
/data/models/audio

/data/cache
/data/cache/huggingface
/data/cache/torch
/data/cache/comfyui
/data/cache/vllm
/data/cache/trtllm
/data/cache/pip

/data/outputs
/data/outputs/images
/data/outputs/videos
/data/outputs/audio

/var/log/sparky
/var/lib/sparky
/var/lib/sparky/jobs
```

The actual NVMe mount path must be discovered during preflight.

If Sparky already uses another data mount, update configuration rather than hardcoding `/data`.

---

## 9. Phase 0 — Preflight

### Goal

Verify the machine before heavy installation.

### Tasks

- [ ] Confirm hostname.
- [ ] Confirm LAN IP.
- [ ] Confirm DNS resolution from MiMi to Sparky.
- [ ] Confirm SSH access.
- [ ] Confirm OS version.
- [ ] Confirm architecture is `aarch64`.
- [ ] Confirm DGX Spark hardware is detected.
- [ ] Confirm GPU and unified memory visibility.
- [ ] Confirm NVMe storage size and mount path.
- [ ] Confirm free disk space.
- [ ] Confirm internet access for model downloads.
- [ ] Confirm access to Hugging Face and NVIDIA NGC if required.
- [ ] Confirm no secrets are committed.

### Commands

```bash
uname -a
uname -m
hostnamectl
ip addr
df -h
lsblk
free -h
nvidia-smi || true
docker --version || true
```

### Acceptance criteria

- [ ] Sparky is reachable over SSH.
- [ ] Hardware and storage are documented in `docs/operations.md`.
- [ ] Model/output/cache paths are confirmed.
- [ ] No secrets are committed.

---

## 10. Phase 1 — Base OS, Storage, and Security

### Goal

Prepare Sparky as a stable AI appliance.

### Tasks

- [ ] Update OS packages.
- [ ] Set hostname to `sparky`.
- [ ] Configure timezone.
- [ ] Configure SSH hardening.
- [ ] Disable password SSH login if SSH keys are ready.
- [ ] Create `sparky` service user.
- [ ] Create required directories.
- [ ] Configure firewall.
- [ ] Allow only required internal ports.
- [ ] Add `.env.example`.
- [ ] Add `config/sparky.env.example`.
- [ ] Add secret handling documentation.
- [ ] Add config backup notes.

### Secrets sourcing — non-negotiable

Sparky must not commit secrets and must not invent its own secret store. The agreed sources of truth are:

```text
SPARKY_API_KEY                 → MiMi-Secrets repo, sealed secret name "sparky-api-key"
                                 mirrored to Sparky host as /etc/sparky/sparky.env (mode 0640, root:sparky)
HF_TOKEN, NGC_API_KEY          → ansible-vault file inventory/group_vars/sparky.yml
                                 (gitignored; only sparky.yml.example is committed)
container env files            → /etc/sparky/sparky.env, mounted read-only into Compose services
sealed-secrets master key      → owned by MiMi, never copied to Sparky
```

Rules:

- The agent generates `SPARKY_API_KEY` once with `openssl rand -hex 32`, registers it as a sealed secret in `MiMi-Secrets` (so MiMi's AI Router can resolve it), and writes it to `/etc/sparky/sparky.env` on Sparky.
- `inventory/group_vars/sparky.yml` is encrypted with `ansible-vault`. The vault password lives in `~/.ansible-vault-pass` on the operator's workstation, never in the repo.
- Compose services receive secrets only through `env_file: /etc/sparky/sparky.env` or Docker secrets — never via `environment:` literals in committed YAML.
- Logs and stack traces must redact any value whose env key matches `*_KEY`, `*_TOKEN`, `*_SECRET`, or `Authorization: Bearer *`.
- `gitleaks` runs in CI (§22) and pre-commit; any commit that introduces a secret is rejected.

### Firewall target

Allow:

```text
22/tcp from admin network
8080/tcp from MiMi/Darkbase network
9100/tcp from MiMi monitoring only
9400/tcp from MiMi monitoring only, if GPU exporter is enabled
```

Block direct external access to:

```text
8000
8001
8188
9001
9002
```

unless explicitly proxied through the authenticated gateway.

### Acceptance criteria

- [ ] Stable hostname.
- [ ] Required directories exist.
- [ ] Firewall active.
- [ ] SSH hardened.
- [ ] Secrets not committed.

---

## 11. Phase 2 — Container Runtime and NVIDIA Validation

### Goal

Ensure NVIDIA containers can use the DGX Spark acceleration stack.

### Tasks

- [ ] Install or verify Docker.
- [ ] Install or verify Docker Compose.
- [ ] Install or verify NVIDIA Container Toolkit.
- [ ] Verify CUDA visibility inside container.
- [ ] Verify PyTorch CUDA inside container.
- [ ] Verify enough unified memory is visible for large models.
- [ ] Add `scripts/check-gpu.sh`.

### Validation commands

```bash
docker --version
docker compose version
nvidia-smi || true
docker run --rm --gpus all nvidia/cuda:latest nvidia-smi
```

If the generic CUDA image is not compatible with DGX Spark, use the NVIDIA-recommended DGX Spark container image.

### Acceptance criteria

- [ ] Container can see NVIDIA device.
- [ ] Container can run CUDA/PyTorch validation.
- [ ] `scripts/check-gpu.sh` reports success.
- [ ] Results are recorded in `docs/operations.md`.

---

## 12. Phase 3 — Sparky Gateway

### Goal

Create the stable authenticated API surface for all external services.

### Preferred stack

```text
Python 3.12+
FastAPI
Pydantic
httpx
uvicorn
prometheus-client
```

### Gateway requirements

- [ ] API key authentication.
- [ ] Request IDs.
- [ ] Structured JSON logs.
- [ ] Timeout handling.
- [ ] Error normalization.
- [ ] No secret logging.
- [ ] Model registry endpoint.
- [ ] Health and readiness endpoints.
- [ ] Metrics endpoint.
- [ ] Reverse proxy support for local model runtimes.
- [ ] Async job submission for long-running jobs.

### Required routes

```text
GET  /health
GET  /ready
GET  /v1/models
GET  /metrics

POST /v1/chat/completions
POST /v1/reasoning/analyze
POST /v1/reasoning/compare

POST /v1/agentic-rag/plan
POST /v1/agentic-rag/evaluate-evidence
POST /v1/agentic-rag/verify
POST /v1/agentic-rag/synthesize
POST /v1/agentic-rag/finalize

POST /v1/coding/review
POST /v1/coding/architecture
POST /v1/coding/refactor-plan
POST /v1/coding/security-review

POST /v1/media/image/jobs
POST /v1/media/video/jobs

POST /v1/audio/tts/jobs
POST /v1/audio/asr/jobs

GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
```

### Acceptance criteria

- [ ] `/health` works.
- [ ] `/ready` reports dependency readiness.
- [ ] Unauthorized requests are rejected.
- [ ] Authorized requests are accepted.
- [ ] Request IDs appear in logs.
- [ ] MiMi can call the gateway from the LAN.
- [ ] Raw runtime ports are not exposed externally.

---

## 13. Phase 4 — Premium Text Runtime: Nemotron 3 Super

### Goal

Run Sparky's main intelligence model.

Primary model:

```text
nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4
```

Primary runtime:

```text
vLLM nightly
```

Secondary optimization target:

```text
TensorRT-LLM
```

### 13.1 vLLM first

Tasks:

- [ ] Follow NVIDIA DGX Spark Nemotron deployment guide.
- [ ] Use the NVFP4 checkpoint.
- [ ] Use NVIDIA-recommended vLLM nightly/container.
- [ ] Bind vLLM to `127.0.0.1:8000`.
- [ ] Expose through Sparky Gateway.
- [ ] Add model to `config/model-registry.yaml`.
- [ ] Add `scripts/start-nemotron-vllm.sh`.
- [ ] Add `scripts/smoke-test-text.sh`.
- [ ] Record memory usage, first-token latency, tokens/sec.

### 13.2 TensorRT-LLM second

Tasks:

- [ ] Implement only after vLLM is stable in production for ≥ 7 days.
- [ ] Follow NVIDIA DGX Spark / TensorRT-LLM guidance.
- [ ] Keep vLLM as working baseline.
- [ ] Benchmark vLLM vs TensorRT-LLM with the §22 Phase 13 / §23 Phase 14 procedures.
- [ ] Choose default runtime based on stability, latency, throughput, and memory.

Promotion rule (mandatory):

- [ ] vLLM remains the default until TensorRT-LLM has run **two consecutive weeks** without crashes, OOMs, or quality regressions.
- [ ] TRT-LLM becomes default only via an explicit PR that flips `runtime: vllm` → `runtime: trtllm` in `config/model-registry.yaml`.
- [ ] vLLM must remain installed and runnable as a fallback for at least one release cycle after TRT-LLM is promoted.
- [ ] If TRT-LLM is rolled back, the registry change is reverted in the same PR; do not delete vLLM.

### Required behavior

The premium text runtime must:

- [ ] support OpenAI-compatible chat/completions through the gateway
- [ ] support long structured prompts
- [ ] return clear errors when unavailable
- [ ] not expose raw vLLM port outside Sparky
- [ ] be restartable by systemd/compose
- [ ] log model load/unload events

### Acceptance criteria

- [ ] Nemotron 3 Super loads successfully.
- [ ] `/v1/chat/completions` returns valid output.
- [ ] Gateway can proxy to Nemotron.
- [ ] Smoke test passes.
- [ ] Benchmark saved to `docs/benchmark-results.md`.

---

## 14. Phase 5 — Agentic RAG Implementation

### Goal

Implement Sparky's premium agentic RAG brain.

Sparky does not own Qdrant or Postgres.
Sparky owns the intelligence stages of agentic RAG.

### Tasks

- [ ] Implement `/v1/agentic-rag/plan`.
- [ ] Implement `/v1/agentic-rag/evaluate-evidence`.
- [ ] Implement `/v1/agentic-rag/synthesize`.
- [ ] Implement `/v1/agentic-rag/verify`.
- [ ] Implement `/v1/agentic-rag/finalize`.
- [ ] Add prompt templates for planning, evaluation, synthesis, and verification.
- [ ] Add strict JSON schema validation.
- [ ] Add tests with sample evidence packs.
- [ ] Add `scripts/smoke-test-agentic-rag.sh`.
- [ ] Document the full protocol in `docs/agentic-rag.md`.

### Agentic RAG quality rules

- [ ] Every important claim must be traceable to supplied evidence.
- [ ] Unsupported claims must be listed separately.
- [ ] Contradictions must be flagged.
- [ ] The model must be allowed to request more retrieval.
- [ ] Source IDs and chunk IDs must not be lost.
- [ ] The final answer must include confidence.
- [ ] The system must prefer saying “insufficient evidence” over guessing.

### Acceptance criteria

- [ ] Sparky generates retrieval plans.
- [ ] Sparky evaluates evidence packs.
- [ ] Sparky requests follow-up retrieval when needed.
- [ ] Sparky synthesizes citation-aware answers.
- [ ] Sparky verifies answer claims against evidence.
- [ ] MiMi can complete one full agentic RAG loop using Sparky.

---

## 15. Phase 6 — Coding Intelligence

### Goal

Use Sparky for premium coding review, architecture decisions, and deep debugging.

### Required endpoints

```text
POST /v1/coding/review
POST /v1/coding/architecture
POST /v1/coding/refactor-plan
POST /v1/coding/security-review
```

### Review request

```json
{
  "task": "review|architecture|debug|refactor-plan|security-review",
  "repository": "string",
  "language": "go|typescript|python|yaml|mixed",
  "files": [
    {
      "path": "string",
      "content": "string"
    }
  ],
  "diff": "string",
  "instructions": "string"
}
```

### Review response

```json
{
  "summary": "string",
  "findings": [
    {
      "severity": "critical|high|medium|low|nit",
      "path": "string",
      "line": 0,
      "title": "string",
      "explanation": "string",
      "recommendation": "string"
    }
  ],
  "architecture_notes": ["string"],
  "tests_to_add": ["string"],
  "final_recommendation": "approve|request_changes|needs_human_review"
}
```

### Acceptance criteria

- [ ] Sparky can review a real diff.
- [ ] Findings are structured.
- [ ] Critical issues are separated from style issues.
- [ ] Architecture notes are useful and specific.
- [ ] Output can be consumed by Maestro or a PR-review workflow.

---

## 16. Phase 7 — Media Runtime: Image and Video

### Goal

Run premium image and video generation workflows.

Runtime:

```text
ComfyUI
```

### Approved image models

```text
FLUX.2
Qwen-Image latest
HunyuanImage-3.0 / Instruct
```

### Approved video models

```text
LTX-2
Wan 2.2
HunyuanVideo-1.5
```

### Tasks

- [ ] Install ComfyUI in containerized form where practical.
- [ ] Store workflows under `/opt/sparky/config/comfyui/workflows`.
- [ ] Store models under `/data/models/image` and `/data/models/video`.
- [ ] Store outputs under `/data/outputs/images` and `/data/outputs/videos`.
- [ ] Add ComfyUI health check.
- [ ] Add gateway media job endpoints.
- [ ] Add job status endpoint.
- [ ] Add output path registration.
- [ ] Add cleanup policy.
- [ ] Add smoke tests.

### Image job request

```json
{
  "model": "flux2|qwen-image|hunyuanimage-3",
  "prompt": "string",
  "negative_prompt": "string",
  "width": 1024,
  "height": 1024,
  "steps": 30,
  "seed": 123,
  "metadata": {}
}
```

### Video job request

```json
{
  "model": "ltx-2|wan-2.2|hunyuanvideo-1.5",
  "prompt": "string",
  "duration_seconds": 5,
  "width": 1280,
  "height": 720,
  "fps": 24,
  "seed": 123,
  "metadata": {}
}
```

### Acceptance criteria

- [ ] ComfyUI starts reliably.
- [ ] FLUX.2 image workflow works.
- [ ] Qwen-Image workflow works.
- [ ] HunyuanImage workflow works if current runtime is available.
- [ ] LTX-2 video workflow works.
- [ ] Wan 2.2 workflow works.
- [ ] HunyuanVideo-1.5 workflow works.
- [ ] Jobs return `job_id`.
- [ ] Outputs are written to `/data/outputs`.
- [ ] Job status can be queried through the gateway.

---

## 17. Phase 8 — Audio and Speech

### Goal

Add premium speech generation and speech recognition.

Approved models:

```text
Qwen3-TTS
VoxCPM2
Qwen3-ASR
```

### Tasks

- [ ] Create audio service container.
- [ ] Add model-specific loaders.
- [ ] Store models under `/data/models/audio`.
- [ ] Store generated audio under `/data/outputs/audio`.
- [ ] Expose through Sparky Gateway.
- [ ] Add health checks.
- [ ] Add smoke tests.
- [ ] Add output cleanup policy.

### TTS request

```json
{
  "model": "qwen3-tts|voxcpm2",
  "text": "string",
  "language": "en|et|multi",
  "voice": "default",
  "style": "calm|professional|energetic|narration",
  "metadata": {}
}
```

### ASR request

```json
{
  "model": "qwen3-asr",
  "input_uri": "file:///data/outputs/audio/input.wav",
  "language": "auto|en|et",
  "metadata": {}
}
```

### Acceptance criteria

- [ ] Qwen3-TTS produces valid audio.
- [ ] VoxCPM2 produces valid audio.
- [ ] Qwen3-ASR transcribes a test file.
- [ ] Jobs are tracked through the gateway.
- [ ] Output paths are returned to MiMi.

---

## 18. Phase 9 — Job Execution Model

### Goal

Long-running media and audio work must not block API calls.

### First implementation

Use a local file-backed job registry:

```text
/var/lib/sparky/jobs
```

### Job states

```text
queued
running
completed
failed
cancelled
```

### Job record

```json
{
  "job_id": "uuid",
  "type": "image|video|tts|asr",
  "model": "string",
  "status": "queued|running|completed|failed|cancelled",
  "created_at": "timestamp",
  "started_at": "timestamp",
  "completed_at": "timestamp",
  "output_uri": "string",
  "error": "string"
}
```

### Acceptance criteria

- [ ] Media/audio jobs return quickly with `job_id`.
- [ ] Job status can be queried.
- [ ] Failed jobs return useful errors.
- [ ] Long-running jobs do not block the gateway.

---

## 19. Phase 10 — Monitoring and Observability

### Goal

MiMi Grafana should show Sparky health.

### Metrics to expose

```text
System:
- CPU usage
- RAM usage
- disk usage
- network throughput
- uptime

GPU / accelerator:
- GPU utilization
- memory usage
- temperature
- power draw if available
- runtime health

Services:
- gateway request count
- gateway error count
- request latency
- active jobs
- failed jobs
- model loaded/unloaded state
- tokens/sec
- image/video/audio job duration
```

### Tasks

- [ ] Install node exporter or equivalent.
- [ ] Install NVIDIA/DCGM exporter if supported on DGX Spark.
- [ ] Add `/metrics` to Sparky Gateway.
- [ ] Configure logging per the rules below.
- [ ] Add MiMi scrape config documentation.
- [ ] Add Grafana dashboard notes.

### Logging rules

- [ ] All Sparky services log structured JSON to `stdout`.
- [ ] Compose services use the `journald` driver with `tag={{.Name}}` so `journalctl -u sparky-*` works.
- [ ] systemd-managed services drop a logrotate file in `/etc/logrotate.d/sparky` that rotates daily, keeps 14 days, compresses, and uses `copytruncate`.
- [ ] Mirror service logs to `/var/log/sparky/<service>/<service>.log` via a journald → file shipper (or a Compose `volumes` bind for services that write directly).
- [ ] Prompts and request bodies are logged at `DEBUG` only and never include secrets (apply the redaction rule from §10 Secrets sourcing).
- [ ] Forwarding logs to MiMi (Loki / promtail) is **out of scope for Phase 10**; document it as a follow-up in `docs/operations.md` so MiMi can pull when it's ready.

### Acceptance criteria

- [ ] MiMi Prometheus can scrape Sparky.
- [ ] Grafana can show Sparky health.
- [ ] Gateway metrics are visible.
- [ ] Model/job failures are observable.

---

## 20. Phase 11 — Security

### Required controls

- [ ] API key authentication (rotation procedure documented in `docs/operations.md`).
- [ ] Firewall rules.
- [ ] SSH key-only access.
- [ ] No public internet exposure.
- [ ] No secrets committed (gitleaks in CI + pre-commit, see §22).
- [ ] `.env.example` only — real env file lives at `/etc/sparky/sparky.env` (mode 0640, root:sparky).
- [ ] `inventory/group_vars/sparky.yml` is `ansible-vault`-encrypted; only `sparky.yml.example` is tracked.
- [ ] `SPARKY_API_KEY` is mirrored from `MiMi-Secrets` (sealed secret `sparky-api-key`).
- [ ] Logs redact `*_KEY`, `*_TOKEN`, `*_SECRET`, and `Authorization: Bearer *` values.
- [ ] Generated media outputs must not be world-readable unless explicitly configured.
- [ ] Admin-only access to raw ComfyUI if exposed.

### Future controls

- [ ] mTLS between MiMi and Sparky.
- [ ] Per-service API keys.
- [ ] Request signing.
- [ ] Audit log.
- [ ] Role-based access control for media and RAG jobs.

### Acceptance criteria

- [ ] Unauthorized API requests fail.
- [ ] Only required ports are open.
- [ ] Secrets are not in Git.
- [ ] Security notes exist in `docs/operations.md`.

---

## 21. Phase 12 — Smoke Tests

Implement scripts:

```text
scripts/smoke-test-health.sh
scripts/smoke-test-text.sh
scripts/smoke-test-agentic-rag.sh
scripts/smoke-test-coding.sh
scripts/smoke-test-media.sh
scripts/smoke-test-audio.sh
```

### Required tests

```text
Health:
- /health returns ok
- /ready returns dependency status

Auth:
- request without token fails
- request with token succeeds

Text:
- /v1/chat/completions returns answer from Nemotron

Agentic RAG:
- /v1/agentic-rag/plan returns retrieval plan
- /v1/agentic-rag/evaluate-evidence evaluates evidence
- /v1/agentic-rag/synthesize returns citation-aware answer
- /v1/agentic-rag/verify flags unsupported claim

Coding:
- /v1/coding/review returns structured review

Media:
- image job returns job_id
- job status returns completed/failed
- output file exists

Audio:
- TTS job returns job_id
- ASR job returns job_id
```

---

## 22. Phase 13 — CI and Quality Gates

### Goal

Match the quality bar set by the rest of this workspace (Logos, Echo, Maestro, MaestroUI, EchoUI, LogosUI). No code lands on `main` without lint + tests + secret scan passing.

### Required tooling

```text
# Ansible
ansible-lint        — playbooks/ + roles/
yamllint            — *.yml / *.yaml

# Python services (sparky-gateway, sparky-worker)
ruff                — lint + format
mypy                — type check (strict for src/)
pytest              — unit tests under services/*/tests/
pytest-asyncio      — for FastAPI async handlers
httpx               — test client

# Repo-wide
gitleaks            — secret scan
markdownlint-cli2   — *.md
shellcheck          — scripts/*.sh
pre-commit          — runs the above locally before commit
```

### Tasks

- [ ] Add `.pre-commit-config.yaml` wiring ruff, yamllint, ansible-lint, gitleaks, markdownlint, shellcheck.
- [ ] Add `.ansible-lint` and `.yamllint` matching MiMi/DarkBase conventions.
- [ ] Add `pyproject.toml` ruff/mypy/pytest config in each service.
- [ ] Add `.github/workflows/ci.yml` running on PR and push to `main`.
- [ ] CI must run all of: ruff, mypy, pytest, ansible-lint, yamllint, gitleaks, markdownlint, shellcheck.
- [ ] CI must fail on any high/critical finding.
- [ ] Document how to run the same checks locally in `docs/operations.md`.

### Minimum test coverage at merge

- [ ] `sparky-gateway`: auth, health, model registry endpoint, every router has at least one happy-path and one failure test.
- [ ] `sparky-worker`: job state transitions, idempotent job creation, evict-and-load policy from §4.3.
- [ ] Smoke test scripts (§21) are linted by shellcheck and dry-run-tested in CI.

### Acceptance criteria

- [ ] PR cannot be merged with red checks.
- [ ] `pre-commit run --all-files` passes on a clean checkout.
- [ ] `gitleaks` finds no secrets.
- [ ] All scripts pass shellcheck.

---

## 23. Phase 14 — Benchmarking

Create `docs/benchmark-results.md`.

### Text benchmarks

Record:

```text
model
runtime
container/image tag
prompt tokens
output tokens
time to first token
tokens/sec
memory usage
temperature
notes
```

### Agentic RAG benchmarks

Use at least five test cases:

```text
1. simple evidence-supported answer
2. missing evidence case
3. contradictory evidence case
4. multi-document synthesis
5. coding/design-document synthesis
```

Record:

```text
retrieval rounds requested
evidence sufficiency result
unsupported claims
answer quality notes
latency
```

### Media benchmarks

Record:

```text
model
workflow
resolution
steps
duration
memory usage
generation time
output path
notes
```

### Audio benchmarks

Record:

```text
model
language
input length
output duration
generation time
quality notes
```

---

## 24. Definition of Done

Sparky is considered ready when:

- [ ] Sparky is reachable from MiMi through `sparky.mimi.local`.
- [ ] Sparky Gateway is running on port `8080`.
- [ ] API key authentication works (key sourced from `MiMi-Secrets`).
- [ ] Nemotron 3 Super is served through `/v1/chat/completions`.
- [ ] Reasoning endpoints (`/v1/reasoning/analyze`, `/v1/reasoning/compare`) return the schemas in §5.2.
- [ ] Agentic RAG endpoints are implemented (plan, evaluate, synthesize, verify, finalize).
- [ ] One full agentic RAG loop works from MiMi through Sparky.
- [ ] Coding review endpoint returns structured findings.
- [ ] Image job endpoint works.
- [ ] Video job endpoint works.
- [ ] TTS job endpoint works.
- [ ] ASR job endpoint works.
- [ ] Co-residency policy from §4.3 is enforced (verifiable via `/v1/models` state field).
- [ ] `config/model-registry.yaml` lists every approved model with pinned HF revisions.
- [ ] Metrics are visible in MiMi monitoring.
- [ ] Smoke tests pass.
- [ ] CI is green on `main` (lint + tests + gitleaks).
- [ ] Benchmarks are documented.
- [ ] Raw runtime ports are not exposed directly.
- [ ] No fallback/older models were silently installed.

---

## 25. Implementation Order for Agent

Follow this order strictly:

```text
0. CI scaffolding (pre-commit + GH Actions skeleton, see §22)
   — land first so every later phase merges through green CI
1. Preflight (incl. disk-budget check from §3)
2. Base OS, storage, and security
   — incl. secrets sourcing from §10 (MiMi-Secrets sealed secret + ansible-vault)
3. Container runtime and NVIDIA validation
4. Sparky Gateway with authentication, model registry, and /v1/models
5. Nemotron vLLM serving
6. OpenAI-compatible chat endpoint
7. Reasoning analyze + compare endpoints
8. Agentic RAG plan / evaluate / synthesize / verify / finalize endpoints
9. Coding intelligence endpoints
10. ComfyUI media runtime
11. Image generation jobs (one image model at a time per §4.3)
12. Video generation jobs
13. Audio/TTS service
14. ASR service
15. Monitoring + logging (§19)
16. Security hardening pass (§20)
17. Full CI bar enforced (§22)
18. Smoke tests (§21)
19. Benchmarks (§23)
20. TensorRT-LLM optimization track (only after vLLM stable for ≥ 7 days, §13.2)
21. Documentation cleanup
```

Do not start media/audio before the gateway and Nemotron text path are stable.

Within each phase, finish P0 capabilities before P1 before P2 (priorities defined in §3).

---

## 26. Agent Notes

- Prefer official NVIDIA DGX Spark guidance for Nemotron (links pinned in §3).
- Prefer NVIDIA-provided or model-maintainer-supported containers when available.
- Keep raw runtime services local.
- Expose only the Sparky Gateway to MiMi.
- Fail loudly on unsupported model/runtime combinations.
- Do not silently downgrade models or substitute "latest" for an undocumented revision (§3 pin-at-install rule).
- Honor the co-residency policy in §4.3 — never partial-load a model when headroom is insufficient.
- Source secrets only via the channels in §10 (MiMi-Secrets sealed secret + ansible-vault). Never inline secrets in committed YAML.
- Keep `config/model-registry.yaml` and `config/api-contract.yaml` in sync with FastAPI routes; CI in §22 will catch drift.
- Keep implementation modular so MiMi can route tasks cleanly.
- Prioritize reliability over adding more models.
- Record every blocker in `docs/troubleshooting.md`.