# Benchmark results

> Status: stub. Populated by Phase 14 (PLAN.md §23).

## Text — premium reasoning

| Date | Model | Runtime | Container/tag | Prompt tok | Output tok | TTFT (ms) | Tokens/sec | Mem (GB) | Temp | Notes |
|------|-------|---------|---------------|-----------:|-----------:|----------:|-----------:|---------:|------|-------|
| _pending_ | nemotron-3-super-120b-a12b-nvfp4 | vllm | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ | first run |

## Agentic RAG

Five test cases (PLAN §23):

1. Simple evidence-supported answer.
2. Missing-evidence case.
3. Contradictory-evidence case.
4. Multi-document synthesis.
5. Coding/design-document synthesis.

Recorded per case: retrieval rounds requested, evidence sufficiency
result, unsupported claims, answer-quality notes, end-to-end latency.

## Media

| Date | Model | Workflow | Resolution | Steps | Duration | Mem (GB) | Generation time | Output | Notes |
|------|-------|----------|------------|------:|---------:|---------:|----------------:|--------|-------|
| _pending_ | flux2-dev | _tbd_ | 1024×1024 | 30 | n/a | _tbd_ | _tbd_ | _path_ | first run |

## Audio

| Date | Model | Language | Input length | Output duration | Generation time | Quality notes |
|------|-------|----------|-------------:|----------------:|----------------:|---------------|
| _pending_ | qwen3-tts | en | _tbd_ | _tbd_ | _tbd_ | first run |
