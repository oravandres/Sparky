# Agentic RAG

> Status: stub. Implementation arrives in PR 8 (PLAN.md §14, §25 step 8).

## Responsibility split (PLAN §6.1)

- **MiMi** — RAG orchestration, ingestion, Qdrant, Postgres metadata,
  access control, source registry, UI integration.
- **DarkBase RTX 5090** — embeddings, reranking, fast query rewriting,
  fast RAG drafts, Qwen3.6 daily assistant.
- **Sparky DGX Spark** — agentic planning, retrieval-strategy generation,
  evidence-quality evaluation, contradiction analysis, premium synthesis,
  final-answer verification, optional finalize step.

## Stages exposed by Sparky (PLAN §5.3, §6)

1. `POST /v1/agentic-rag/plan` — produce a multi-round retrieval plan
   from the question + available sources (§6.3, §6.4).
2. `POST /v1/agentic-rag/evaluate-evidence` — judge an evidence pack;
   may request follow-up retrieval (§6.5, §6.6).
3. `POST /v1/agentic-rag/synthesize` — citation-aware draft answer
   (§6.7, §6.8).
4. `POST /v1/agentic-rag/verify` — verify claims against evidence
   (§6.9, §6.10).
5. `POST /v1/agentic-rag/finalize` — produce the user-facing answer
   (§6.11). Optional; orchestrators that want manual control can stop
   after `verify`.

## Quality bar (PLAN §14)

- Every important claim is traceable to supplied evidence; unsupported
  claims are surfaced separately, never hidden in the answer.
- Contradictions are flagged with the chunk IDs they came from.
- Sparky may request more retrieval rather than guess.
- "Insufficient evidence" is preferred over fabricated answers.
- Source IDs and chunk IDs round-trip the entire flow.

## Acceptance smoke (PLAN §6.12)

`scripts/smoke-test-agentic-rag.sh` (added in PR 12) walks one full loop
via the gateway with sample evidence packs covering: simple supported
answer, missing-evidence case, contradictory evidence, multi-document
synthesis, design-doc synthesis.
