# Agentic RAG

Sparky owns the **intelligence stages** of the agentic RAG loop. MiMi
still owns Qdrant, Postgres, ingestion, and the retrieval tool calls
themselves (PLAN §6.1). This document describes how the Sparky Gateway
exposes that intelligence, how integrity is enforced, and how callers
wire stages together.

Source of truth for the request/response shapes is
[`config/api-contract.yaml`](../config/api-contract.yaml).
PLAN authority: §5.3, §6, §14.

## Responsibility split (PLAN §6.1)

- **MiMi** — RAG orchestration, ingestion, Qdrant, Postgres metadata,
  access control, source registry, UI integration.
- **DarkBase RTX 5090** — embeddings, reranking, fast query rewriting,
  fast RAG drafts, Qwen3.6 daily assistant.
- **Sparky DGX Spark** — agentic planning, retrieval-strategy generation,
  evidence-quality evaluation, contradiction analysis, premium synthesis,
  final-answer verification, optional finalize step.

## Stages exposed by the gateway

Every route below requires `Authorization: Bearer <SPARKY_API_KEY>` and
is proxied through the always-hot Nemotron text runtime (Tier A of the
§4.3 co-residency policy).

| Method | Path | Purpose | PLAN §§ |
|---|---|---|---|
| POST | `/v1/agentic-rag/plan` | Produce a multi-round retrieval plan from the question + available sources | §6.3, §6.4 |
| POST | `/v1/agentic-rag/evaluate-evidence` | Judge an evidence pack; may request follow-up retrieval | §6.5, §6.6 |
| POST | `/v1/agentic-rag/synthesize` | Citation-aware draft answer from evidence | §6.7, §6.8 |
| POST | `/v1/agentic-rag/verify` | Classify each claim in a draft against evidence | §6.9, §6.10 |
| POST | `/v1/agentic-rag/finalize` | Produce the user-facing answer with citation markers | §6.11 |

`synthesize` + `verify` can be called separately when the orchestrator
wants manual control. `finalize` wraps both into a single step when MiMi
just wants the final answer.

## End-to-end flow (PLAN §6.2)

```text
MiMi (orchestrator)
  │
  ├── POST /v1/agentic-rag/plan
  │     → retrieval_rounds, required_facts, intent
  │
  ├── execute retrieval (Qdrant / Postgres / code search)    ← MiMi
  ├── rerank                                                 ← DarkBase
  │
  ├── POST /v1/agentic-rag/evaluate-evidence
  │     → sufficient? contradictions? recommended_followup_queries?
  │
  ├── (loop retrieval if sufficient=false, up to max_retrieval_rounds)
  │
  ├── POST /v1/agentic-rag/synthesize
  │     → answer, citations[], unsupported_claims[]
  │
  ├── POST /v1/agentic-rag/verify
  │     → supported_claims, unsupported_claims, contradictions,
  │        final_answer_ready
  │
  └── POST /v1/agentic-rag/finalize       (optional, when MiMi wants the
          user-facing answer prepared by Sparky rather than stitched
          client-side)
        → final_answer, marker-style citations, removed_unsupported_claims
```

## Gateway-enforced integrity

The gateway never trusts Nemotron's output to be self-consistent with
the caller's request. Each stage has a post-response check, and schema
drift from the model returns HTTP 502 (`runtime_error`), not HTTP 200
with a subtle corruption:

- **Plan** — `retrieval_rounds` ≤ `constraints.max_retrieval_rounds`,
  round numbers unique, and `retrieval_rounds` is empty when
  `needs_rag=false`.
- **Evaluate** — every `contradictions[].chunk_ids` entry must be a
  `chunk_id` that appeared in the request's `evidence_chunks`. Invented
  ids are rejected.
- **Synthesize** — every `citations[*].(source_id, chunk_id)` pair must
  match a supplied chunk. `unsupported_claims` are surfaced separately,
  never hidden inside the answer.
- **Verify** — the model may only classify claims; it cannot introduce
  new ones. Free-form strings are returned as-is, but confidence and
  `final_answer_ready` are validated against the enum contract.
- **Finalize** — citations are checked the same way as synthesize, and
  `citations[*].marker` must be unique (so inline `[1]` / `[2]` markers
  cannot collide).

Authentication, body size caps, and the approved-model registry gate
(PLAN §2.2, §12) are shared with the rest of the gateway.

## Model and budget defaults

All five stages default to the premium reasoning model
(`nemotron-3-super-120b-a12b-nvfp4`, PLAN §3). Per-stage max-token
budgets are tunable through `config/sparky.env`:

```bash
SPARKY_AGENTIC_RAG_MODEL_ID=nemotron-3-super-120b-a12b-nvfp4
SPARKY_AGENTIC_RAG_TEMPERATURE=0.2
SPARKY_AGENTIC_RAG_PLAN_MAX_TOKENS=2048
SPARKY_AGENTIC_RAG_EVALUATE_MAX_TOKENS=2048
SPARKY_AGENTIC_RAG_SYNTHESIZE_MAX_TOKENS=4096
SPARKY_AGENTIC_RAG_VERIFY_MAX_TOKENS=2048
SPARKY_AGENTIC_RAG_FINALIZE_MAX_TOKENS=4096
```

The gateway will clamp a caller's `synthesize.max_tokens` to
`SPARKY_AGENTIC_RAG_SYNTHESIZE_MAX_TOKENS`; the upstream budget is the
minimum of the two. Concurrency is throttled by the shared Nemotron
semaphore (`SPARKY_NEMOTRON_MAX_INFLIGHT`).

## Quality bar (PLAN §14)

- Every important claim is traceable to supplied evidence; unsupported
  claims are surfaced separately, never hidden in the answer.
- Contradictions are flagged with the chunk ids they came from.
- Sparky may request more retrieval rather than guess.
- "Insufficient evidence" is preferred over fabricated answers.
- Source ids and chunk ids round-trip the entire flow.

## Acceptance tests (PLAN §6.12)

Unit coverage lives in
[`services/sparky-gateway/tests/test_agentic_rag.py`](../services/sparky-gateway/tests/test_agentic_rag.py)
and covers, per stage: auth, schema validation, happy-path proxy,
upstream failure, and the gateway-enforced integrity checks above.

`scripts/smoke-test-agentic-rag.sh` (added in the Phase 12 smoke-tests
PR, PLAN §21) walks one full loop via the gateway with sample evidence
packs covering: simple supported answer, missing-evidence case,
contradictory evidence, multi-document synthesis, and design-doc
synthesis.
