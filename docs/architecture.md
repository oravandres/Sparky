# Architecture

> Status: stub. Full content lands as later phases complete (PLAN.md §25).

This document captures the as-built architecture of Sparky once the gateway,
runtimes, and workers are deployed. The authoritative design lives in
[`PLAN.md`](../PLAN.md) — particularly:

- §1 — Target architecture (MiMi / DarkBase / Sparky split).
- §4 — Service topology and ports (PLAN §4.1).
- §4.3 — Co-residency policy and eviction rules.
- §5 — Public internal API contract (mirrored in
  [`config/api-contract.yaml`](../config/api-contract.yaml)).

When this stub is replaced, include:

- Concrete bind addresses and host paths used by the deployed instance
  (PLAN §8 — `/data/models/*`, `/data/cache/*`, `/data/outputs/*`,
  `/var/lib/sparky/jobs`, `/var/log/sparky`).
- Diagrams of request flow for: chat completions, agentic-RAG (full loop),
  media job submit + poll, audio job submit + poll.
- Co-residency state diagram and worked example of an evict-and-load cycle.
- Resolved storage mount path discovered in preflight.
