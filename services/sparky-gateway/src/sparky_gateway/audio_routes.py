"""POST /v1/audio/{tts,asr}/jobs — TTS and ASR job submission (PLAN §5.6, §17, §18).

Phase 8 (gateway side): callers submit a job describing an approved TTS or
ASR model and the gateway returns ``202`` with ``{job_id, type, "queued"}``.
The actual model invocation happens in the audio service (PLAN §4.1
``sparky-audio`` on ``127.0.0.1:9001``); the gateway never talks to it
directly here — that keeps the gateway thin per ``AGENTS.md`` and PLAN
§4.3 and reuses the file-backed ledger that media submissions already use
(:mod:`~sparky_gateway.job_store`).

Validation responsibilities (mirror ``config/api-contract.yaml``
``TtsJobRequest`` / ``AsrJobRequest``):

* ``model`` must reference an *active* registry entry whose ``family`` is
  ``audio``, whose ``runtime`` is ``audio``, and whose ``role`` matches the
  route (``premium-tts`` for TTS, ``premium-asr`` for ASR). Sparky never
  silently substitutes an older or excluded model (PLAN §2.2).
* TTS: text length, language allow-list, voice/style allow-lists.
* ASR: ``input_uri`` is restricted to ``file:///data/outputs/…`` and
  ``file:///data/models/…`` and is canonicalised against the allow-list
  *before* enqueue so the worker never opens a path outside Sparky's data
  roots (PLAN §17 + §10 secrets/path safety).
"""

from __future__ import annotations

import logging
import re
from pathlib import PurePosixPath
from typing import Any, Final, Literal
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .auth import verify_api_key
from .errors import envelope
from .job_store import JobStore, JobType
from .registry import Model, Registry

log = logging.getLogger("sparky_gateway")

router = APIRouter(tags=["audio"])

# Hard caps mirror config/api-contract.yaml. Pydantic enforces them with
# explicit error envelopes; CI lints both files for drift (PLAN §22).
_TTS_TEXT_MAX_CHARS: Final[int] = 50_000
_VOICE_MAX_CHARS: Final[int] = 64
_INPUT_URI_MAX_CHARS: Final[int] = 4_096

# Allow-list of root prefixes a worker is permitted to open (PLAN §17 + §8
# host paths). Keep these as POSIX paths — the worker container mounts the
# host /data tree at the same location so the canonical form is identical
# in the gateway and in the worker.
_ASR_ALLOWED_ROOTS: Final[tuple[PurePosixPath, ...]] = (
    PurePosixPath("/data/outputs"),
    PurePosixPath("/data/models"),
)

# Mirror of the ECMA-safe regex pinned in config/api-contract.yaml so the
# server-side rejection is identical to the OpenAPI rejection clients see.
# Path traversal (`..`, `%2e%2e`) and any non-allowlisted character class
# fail before we even try to canonicalise the path.
_ASR_INPUT_URI_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^file:///data/(outputs|models)/(?!.*(\.\.|%2[eE]%2[eE]))[\w./-]+$"
)

TtsModelId = Literal["qwen3-tts", "voxcpm2"]
AsrModelId = Literal["qwen3-asr"]
TtsLanguage = Literal["en", "et", "multi"]
AsrLanguage = Literal["auto", "en", "et"]
TtsStyle = Literal["calm", "professional", "energetic", "narration"]


class TtsJobRequestBody(BaseModel):
    """TTS job submission shape (PLAN §17 / api-contract.yaml ``TtsJobRequest``)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model: TtsModelId
    text: str = Field(min_length=1, max_length=_TTS_TEXT_MAX_CHARS)
    language: TtsLanguage | None = None
    voice: str = Field(default="default", min_length=1, max_length=_VOICE_MAX_CHARS)
    style: TtsStyle | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AsrJobRequestBody(BaseModel):
    """ASR job submission shape (PLAN §17 / api-contract.yaml ``AsrJobRequest``)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    model: AsrModelId
    input_uri: str = Field(min_length=1, max_length=_INPUT_URI_MAX_CHARS)
    language: AsrLanguage | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_uri")
    @classmethod
    def _input_uri_is_allowed(cls, value: str) -> str:
        # Step 1: cheap regex gate (parity with the OpenAPI ``pattern``).
        # We must reject before any path math so a malformed scheme cannot
        # influence ``urlsplit`` heuristics.
        if not _ASR_INPUT_URI_PATTERN.fullmatch(value):
            raise ValueError(
                "input_uri must be a file:// URI under /data/outputs/ or /data/models/ "
                "with no traversal (.., %2e%2e)"
            )

        # Step 2: canonicalise. The regex above already restricts the scheme
        # to ``file:///`` (triple slash → empty authority); we re-parse so we
        # operate on the percent-decoded path the worker will eventually
        # open. The contract intentionally rejects ``file://localhost/…`` so
        # there is exactly one canonical form on the wire — staying aligned
        # with the OpenAPI ``pattern`` keeps generated clients honest.
        parsed = urlsplit(value)
        if parsed.scheme != "file" or parsed.netloc != "":
            raise ValueError(
                "input_uri scheme must be file:// with an empty authority "
                "(use file:///data/…, not file://localhost/data/…)"
            )

        decoded = unquote(parsed.path)
        try:
            candidate = PurePosixPath(decoded)
        except (TypeError, ValueError) as exc:
            raise ValueError("input_uri path is not a valid POSIX path") from exc
        if not candidate.is_absolute():
            raise ValueError("input_uri path must be absolute under /data/")

        # ``PurePosixPath`` does not collapse ``..`` segments, but the regex
        # above already excluded them. Belt-and-braces: explicitly reject
        # any residual ``..`` part (handles ``/data/outputs/./..`` style).
        if any(part == ".." for part in candidate.parts):
            raise ValueError("input_uri path must not contain '..' traversal")

        if not any(_is_within(candidate, root) for root in _ASR_ALLOWED_ROOTS):
            raise ValueError("input_uri must reside under /data/outputs/ or /data/models/")

        return value


def _is_within(candidate: PurePosixPath, root: PurePosixPath) -> bool:
    """Return ``True`` iff ``candidate`` is ``root`` or a descendant of it.

    Pure POSIX comparison only — the gateway never touches the filesystem
    here. The worker is responsible for the final ``open`` and stat dance.
    """
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _require_audio_model(
    registry: Registry,
    *,
    model_id: str,
    expected_role: Literal["premium-tts", "premium-asr"],
    rid: str | None,
) -> Model:
    """Resolve ``model_id`` against the registry and enforce route invariants."""
    m = registry.by_id(model_id)
    if m is None or not m.active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "unapproved_model",
                f"model {model_id!r} is not an active entry in the Sparky registry",
                rid,
            ),
        )
    if m.family != "audio":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                (
                    f"model {model_id!r} (family={m.family!r}) is not valid for "
                    "the audio jobs endpoints"
                ),
                rid,
            ),
        )
    if m.runtime != "audio":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                f"model {model_id!r} must use the audio runtime for audio jobs",
                rid,
            ),
        )
    if m.role != expected_role:
        # Prevents callers from using a TTS model on the ASR endpoint and
        # vice-versa even when both share the audio runtime.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=envelope(
                "invalid_model_for_route",
                (
                    f"model {model_id!r} (role={m.role!r}) is not valid for the "
                    f"{expected_role!r} endpoint"
                ),
                rid,
            ),
        )
    return m


def _accepted_payload(*, job_id: str, job_type: JobType) -> dict[str, str]:
    """Stable JobAccepted envelope (PLAN §5.7, OpenAPI ``JobAccepted``)."""
    return {"job_id": job_id, "type": job_type, "status": "queued"}


async def _enqueue_or_503(
    *,
    store: JobStore,
    job_type: JobType,
    model: str,
    request_payload: dict[str, Any],
    rid: str | None,
) -> JSONResponse:
    """Common create + redacted-503 mapping shared by tts/asr routes.

    Mirrors the media-route helper: ``OSError`` from
    :meth:`JobStore._ensure_dir` indicates a missing or read-only host
    bind-mount (PLAN §8 / docker-compose.gateway.yml). The gateway returns
    a stable ``503 jobs_dir_unavailable`` envelope so callers backoff while
    operators fix the mount; the path itself stays in request-id-tagged
    logs (PLAN §10 redaction rule).
    """
    try:
        record = await store.create(
            job_type=job_type,
            model=model,
            request=request_payload,
        )
    except OSError as exc:
        log.error(
            "audio_job_jobs_dir_unwritable",
            extra={
                "request_id": rid,
                "job_type": job_type,
                "model": model,
                "error": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=envelope(
                "jobs_dir_unavailable",
                "job ledger is not writable; consult gateway logs using request_id",
                rid,
            ),
        ) from exc
    log.info(
        f"audio_{job_type}_job_accepted",
        extra={"request_id": rid, "job_id": record.job_id, "model": model},
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=_accepted_payload(job_id=record.job_id, job_type=job_type),
    )


@router.post(
    "/v1/audio/tts/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def submit_tts_job(
    request: Request,
    body: TtsJobRequestBody,
) -> JSONResponse:
    """Submit a text-to-speech job (PLAN §5.6, §17)."""
    rid = getattr(request.state, "request_id", None)
    registry: Registry = request.app.state.registry
    _require_audio_model(
        registry,
        model_id=body.model,
        expected_role="premium-tts",
        rid=rid,
    )

    store: JobStore = request.app.state.job_store
    return await _enqueue_or_503(
        store=store,
        job_type="tts",
        model=body.model,
        request_payload=body.model_dump(exclude_none=True),
        rid=rid,
    )


@router.post(
    "/v1/audio/asr/jobs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def submit_asr_job(
    request: Request,
    body: AsrJobRequestBody,
) -> JSONResponse:
    """Submit an automatic-speech-recognition job (PLAN §5.6, §17)."""
    rid = getattr(request.state, "request_id", None)
    registry: Registry = request.app.state.registry
    _require_audio_model(
        registry,
        model_id=body.model,
        expected_role="premium-asr",
        rid=rid,
    )

    store: JobStore = request.app.state.job_store
    return await _enqueue_or_503(
        store=store,
        job_type="asr",
        model=body.model,
        request_payload=body.model_dump(exclude_none=True),
        rid=rid,
    )
