# Audio (TTS + ASR)

Sparky exposes async text-to-speech (TTS) and automatic-speech-recognition
(ASR) jobs through the gateway. Submissions are persisted to the same
single-node, file-backed ledger as media jobs and executed by the audio
service ([`sparky-audio`](../services/) on `127.0.0.1:9001`, PLAN §4.1)
which polls the ledger and drives the model. The source of truth for
request/response shapes is
[`config/api-contract.yaml`](../config/api-contract.yaml); PLAN authority:
§5.6 (audio), §5.7 (job control), §17 (audio runtime), §18 (job execution
model).

## Endpoints exposed by the gateway

Every route below requires `Authorization: Bearer <SPARKY_API_KEY>`
(PLAN §5, §10).

| Method | Path                          | Returns | PLAN §§      |
| ------ | ----------------------------- | ------- | ------------ |
| POST   | `/v1/audio/tts/jobs`          | `202`   | §5.6, §17    |
| POST   | `/v1/audio/asr/jobs`          | `202`   | §5.6, §17    |
| GET    | `/v1/jobs/{job_id}`           | `200`   | §5.7, §18    |
| POST   | `/v1/jobs/{job_id}/cancel`    | `200`   | §5.7, §18    |

`/v1/jobs/*` are shared between media (image, video) and audio (tts, asr).
The persisted record carries a `type` field so consumers branch on the
job class without polling per-family endpoints — see
[`media.md`](media.md) for the same shape.

## TTS jobs (`POST /v1/audio/tts/jobs`)

```json
{
  "model": "qwen3-tts | voxcpm2",
  "text": "string (1..50000 chars)",
  "language": "en | et | multi (optional)",
  "voice": "default",
  "style": "calm | professional | energetic | narration (optional)",
  "metadata": { }
}
```

Validation that fails with HTTP **422** before enqueue:

- `text` is required, non-empty, and ≤ 50 000 characters.
- `voice` is ≤ 64 characters; defaults to `default`.
- `language` and `style` use a closed enum (sending `xx` or `screaming`
  is rejected).
- `model` must reference an *active* registry entry whose `family` is
  `audio`, whose `runtime` is `audio`, **and whose `role` is
  `premium-tts`** — using an ASR model on the TTS endpoint is a route
  mismatch.
- Excluded models (`kokoro`, `fish-speech`, `cosyvoice`, `whisper`,
  `faster-whisper`, …) are rejected explicitly — Sparky never silently
  substitutes an older model (PLAN §2.2).

A successful submission returns `JobAccepted`:

```json
{
  "job_id": "uuid",
  "type": "tts",
  "status": "queued"
}
```

## ASR jobs (`POST /v1/audio/asr/jobs`)

```json
{
  "model": "qwen3-asr",
  "input_uri": "file:///data/outputs/audio/clip.wav",
  "language": "auto | en | et (optional)",
  "metadata": { }
}
```

Validation that fails with HTTP **422** before enqueue (PLAN §17 + §10
path safety):

- `input_uri` must match the OpenAPI pattern
  `^file:///data/(outputs|models)/…` and reject `..` and `%2e%2e` /
  `%2E%2E`-style traversal.
- The gateway then re-parses the URI server-side, percent-decodes the
  path, and verifies it canonicalises **under** one of the allow-listed
  roots `/data/outputs/` or `/data/models/`. Anything outside (e.g.
  `/etc/passwd`, `/data/cache/leak.wav`, `/opt/sparky/config/sparky.env`)
  is refused.
- The URI scheme must be `file://` with an **empty authority**
  (`file:///data/…`, the standard triple-slash form). Both
  `file://localhost/data/outputs/x.wav` and
  `file://attacker.example.com/data/outputs/x.wav` are rejected so
  there is exactly one canonical form on the wire — the OpenAPI
  `pattern` and the gateway agree.
- `model` must be an *active* registry entry with role `premium-asr`
  using the audio runtime — sending a TTS model is rejected.

A successful submission returns:

```json
{
  "job_id": "uuid",
  "type": "asr",
  "status": "queued"
}
```

## Job control

See [`media.md`](media.md#job-control-v1jobsjob_id) — the same
`/v1/jobs/{job_id}` and `/v1/jobs/{job_id}/cancel` endpoints serve audio
jobs. The persisted record's `type` field is `tts` or `asr` for audio,
mirroring `image` / `video` for media.

## File-backed job ledger (PLAN §18)

The gateway writes one JSON file per job under `JOBS_DIR` (default
`/var/lib/sparky/jobs`, see `config/sparky.env.example`). Audio
submissions reuse the same store and atomic-write contract as media
submissions; see [`media.md`](media.md#file-backed-job-ledger-plan-18)
for the full provisioning + boot-resilience story.

Both audio routes return **`503 jobs_dir_unavailable`** when the host
forgot to bind-mount the writable jobs directory — same envelope as the
media routes so MiMi can use one retry/backoff policy across all
async submissions.

## Acceptance tests (PLAN §17, §18, §21)

Unit coverage:

- [`services/sparky-gateway/tests/test_audio.py`](../services/sparky-gateway/tests/test_audio.py)
  — TTS / ASR schema gates, registry coupling, ASR URI sanitisation
  (regex + canonical path + scheme), contract parity, 503 fallback.
- [`services/sparky-gateway/tests/test_jobs.py`](../services/sparky-gateway/tests/test_jobs.py)
  — shared GET / cancel state machine (used by audio identically).

[`scripts/smoke-test-audio.sh`](../scripts/smoke-test-audio.sh) (PLAN §21)
exercises submit → query → cancel against a running gateway. The audio
service is **not** required for the smoke test — the gateway only
enqueues; actual TTS/ASR execution is the audio service's job (PLAN
§4.1).
