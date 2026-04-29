# API contract

> Status: stub. Authoritative shape lives in
> [`config/api-contract.yaml`](../config/api-contract.yaml) (OpenAPI 3.1) and
> [`PLAN.md`](../PLAN.md) §5. This file is the human-readable companion.

## Overview

External consumers (Maestro, AI Router, MaestroUI, DarkBase services, future
coding/media agents) call:

```text
http://sparky.mimi.local:8080
```

with `Authorization: Bearer <SPARKY_API_KEY>` (PLAN §5).

## Endpoint families

- **Health probes**: `/health`, `/ready` — unauthenticated (PLAN §5.1).
- **Telemetry**: `GET /metrics` requires the same Bearer token as other gateway routes (Prometheus scrape uses `Authorization`); PLAN §19 metrics exposure — see OpenAPI for shape.
- **Models**: `GET /v1/models` (PLAN §5.1 + co-residency state from §4.3).
- **Premium text**: `POST /v1/chat/completions`,
  `POST /v1/reasoning/analyze`, `POST /v1/reasoning/compare` (PLAN §5.2).
- **Agentic RAG**: `plan`, `evaluate-evidence`, `synthesize`, `verify`,
  `finalize` under `/v1/agentic-rag/*` (PLAN §5.3, §6).
- **Coding intelligence**: `review`, `architecture`, `refactor-plan`,
  `security-review` under `/v1/coding/*` (PLAN §5.4, §15).
- **Media**: `POST /v1/media/image/jobs`, `POST /v1/media/video/jobs`
  (PLAN §5.5, §16).
- **Audio**: `POST /v1/audio/tts/jobs`, `POST /v1/audio/asr/jobs`
  (PLAN §5.6, §17).
- **Job control (shared)**: `GET /v1/jobs/{job_id}`,
  `POST /v1/jobs/{job_id}/cancel` (PLAN §5.7, §18).

## Validation and limits

The OpenAPI schemas encode guardrails so callers get stable HTTP **422**
responses when a request is out of policy (GPU-heavy dimensions, excessive
duration, unsafe URIs) rather than failing deep inside a worker:

- **Chat**: `POST /v1/chat/completions` validates bounded `max_tokens` before proxy and exposes optional `stream`, which must be
  **`false`** when present (JSON Schema `enum: [false]`). Sending `true`
  fails validation until SSE streaming exists. Other OpenAI-shaped optional keys
  remain allowed via `additionalProperties` where listed.
- **Image / video jobs**: width, height, steps, duration, and fps carry
  explicit min/max and alignment (`multipleOf`) bounds; video defaults cap
  resolution and wall-clock duration to stay within the single ComfyUI slot budget.
- **ASR**: `input_uri` must match `file:///data/(outputs|models)/…` with a schema
  pattern that rejects `..` and `%2e%2e` / `%2E%2E`-style encoding (no regex inline
  flags—ECMA-262 / JS-safe); gateway still canonicalizes paths before opening files.

## Drift policy

`config/api-contract.yaml` is kept in lockstep with the FastAPI route
definitions in `services/sparky-gateway/`. CI (PLAN §22) lints both for
drift; PRs that change a route must update both files in the same change.
