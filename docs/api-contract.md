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

- **Health & telemetry**: `/health`, `/ready`, `/metrics` (PLAN §5.1, §19).
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

- **Chat**: `POST /v1/chat/completions` does **not** expose `stream: true` until
  the gateway implements SSE `text/event-stream` compatible with OpenAI
  streaming clients.
- **Image / video jobs**: width, height, steps, duration, and fps carry
  explicit min/max and alignment (`multipleOf`) bounds matching supported
  ComfyUI workflows.
- **ASR**: `input_uri` must match `file:///data/(outputs|models)/…` only —
  no arbitrary `http(s)://` or other schemes (SSRF prevention).

## Drift policy

`config/api-contract.yaml` is kept in lockstep with the FastAPI route
definitions in `services/sparky-gateway/`. CI (PLAN §22) lints both for
drift; PRs that change a route must update both files in the same change.
