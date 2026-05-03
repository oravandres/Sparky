"""POST /v1/audio/{tts,asr}/jobs — submission validation + enqueue (PLAN §17, §18)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
API_CONTRACT_PATH = REPO_ROOT / "config" / "api-contract.yaml"


def _tts_request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "qwen3-tts",
        "text": "hello world",
    }
    base.update(overrides)
    return base


def _asr_request(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "model": "qwen3-asr",
        "input_uri": "file:///data/outputs/audio/sample.wav",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_tts_jobs_require_auth(client: TestClient) -> None:
    r = client.post("/v1/audio/tts/jobs", json=_tts_request())
    assert r.status_code == 401


def test_asr_jobs_require_auth(client: TestClient) -> None:
    r = client.post("/v1/audio/asr/jobs", json=_asr_request())
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# TTS — happy path + registry / schema gates
# ---------------------------------------------------------------------------


def test_tts_job_happy_path_returns_202(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post("/v1/audio/tts/jobs", headers=auth_header, json=_tts_request())
    assert r.status_code == 202
    body = r.json()
    assert body["type"] == "tts"
    assert body["status"] == "queued"
    UUID(body["job_id"])


def test_tts_job_accepts_each_approved_model(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    for model in ("qwen3-tts", "voxcpm2"):
        r = client.post(
            "/v1/audio/tts/jobs",
            headers=auth_header,
            json=_tts_request(model=model),
        )
        assert r.status_code == 202, f"{model} should be accepted: {r.json()}"


def test_tts_job_persists_record_on_disk(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(language="en", style="calm", voice="narrator-1"),
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    jobs_dir = Path(client.app.state.settings.jobs_dir)
    on_disk = json.loads((jobs_dir / f"{job_id}.json").read_text())
    assert on_disk["status"] == "queued"
    assert on_disk["type"] == "tts"
    assert on_disk["model"] == "qwen3-tts"
    assert on_disk["request"]["text"] == "hello world"
    assert on_disk["request"]["voice"] == "narrator-1"
    assert on_disk["request"]["style"] == "calm"


def test_tts_job_rejects_asr_model(client: TestClient, auth_header: dict[str, str]) -> None:
    """An ASR model on the TTS endpoint is a route mismatch (different role)."""
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(model="qwen3-asr"),
    )
    assert r.status_code == 422


def test_tts_job_rejects_text_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(model="nemotron-3-super-120b-a12b-nvfp4"),
    )
    assert r.status_code == 422


def test_tts_job_rejects_image_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(model="flux2-dev"),
    )
    assert r.status_code == 422


def test_tts_job_rejects_excluded_model(client: TestClient, auth_header: dict[str, str]) -> None:
    """Sparky must never silently substitute Kokoro/CosyVoice/etc. (PLAN §2.2)."""
    for excluded in ("kokoro", "fish-speech", "cosyvoice"):
        r = client.post(
            "/v1/audio/tts/jobs",
            headers=auth_header,
            json=_tts_request(model=excluded),
        )
        assert r.status_code == 422, f"{excluded} should be rejected"


def test_tts_job_requires_text(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json={"model": "qwen3-tts"},
    )
    assert r.status_code == 422


def test_tts_job_rejects_empty_text(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(text=""),
    )
    assert r.status_code == 422


def test_tts_job_rejects_oversized_text(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(text="a" * 50_001),
    )
    assert r.status_code == 422


def test_tts_job_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    payload = _tts_request()
    payload["pitch"] = 1.5
    r = client.post("/v1/audio/tts/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_tts_job_rejects_unknown_language(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(language="xx"),
    )
    assert r.status_code == 422


def test_tts_job_rejects_unknown_style(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(style="screaming"),
    )
    assert r.status_code == 422


def test_tts_job_rejects_oversized_voice(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/tts/jobs",
        headers=auth_header,
        json=_tts_request(voice="v" * 65),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# ASR — happy path + URI sanitisation
# ---------------------------------------------------------------------------


def test_asr_job_happy_path_returns_202(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post("/v1/audio/asr/jobs", headers=auth_header, json=_asr_request())
    assert r.status_code == 202
    body = r.json()
    assert body["type"] == "asr"
    assert body["status"] == "queued"
    UUID(body["job_id"])


def test_asr_job_accepts_models_root(client: TestClient, auth_header: dict[str, str]) -> None:
    """ASR may also transcribe shipped audio assets under /data/models/."""
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(input_uri="file:///data/models/audio/sample.wav"),
    )
    assert r.status_code == 202


def test_asr_job_persists_record_on_disk(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(language="en"),
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    jobs_dir = Path(client.app.state.settings.jobs_dir)
    on_disk = json.loads((jobs_dir / f"{job_id}.json").read_text())
    assert on_disk["type"] == "asr"
    assert on_disk["model"] == "qwen3-asr"
    assert on_disk["request"]["input_uri"].endswith("sample.wav")
    assert on_disk["request"]["language"] == "en"


def test_asr_job_rejects_tts_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(model="qwen3-tts"),
    )
    assert r.status_code == 422


def test_asr_job_rejects_image_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(model="flux2-dev"),
    )
    assert r.status_code == 422


def test_asr_job_requires_input_uri(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json={"model": "qwen3-asr"},
    )
    assert r.status_code == 422


def test_asr_job_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    payload = _asr_request()
    payload["beam_size"] = 8
    r = client.post("/v1/audio/asr/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_asr_job_rejects_dotdot_traversal(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(input_uri="file:///data/outputs/../etc/passwd"),
    )
    assert r.status_code == 422


def test_asr_job_rejects_url_encoded_traversal(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Both lowercase and uppercase percent-encoded `..` must be rejected."""
    for variant in ("%2e%2e", "%2E%2E"):
        r = client.post(
            "/v1/audio/asr/jobs",
            headers=auth_header,
            json=_asr_request(input_uri=f"file:///data/outputs/{variant}/etc/passwd"),
        )
        assert r.status_code == 422, f"variant {variant} should be rejected"


def test_asr_job_rejects_path_outside_data_roots(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Anything outside /data/outputs/ or /data/models/ is rejected."""
    for uri in (
        "file:///etc/passwd",
        "file:///data/cache/leak.wav",
        "file:///opt/sparky/config/sparky.env",
    ):
        r = client.post(
            "/v1/audio/asr/jobs",
            headers=auth_header,
            json=_asr_request(input_uri=uri),
        )
        assert r.status_code == 422, f"uri {uri} should be rejected"


def test_asr_job_rejects_non_file_scheme(client: TestClient, auth_header: dict[str, str]) -> None:
    for uri in (
        "http://example.com/audio.wav",
        "https://example.com/audio.wav",
        "s3://bucket/audio.wav",
        "/data/outputs/audio/sample.wav",
    ):
        r = client.post(
            "/v1/audio/asr/jobs",
            headers=auth_header,
            json=_asr_request(input_uri=uri),
        )
        assert r.status_code == 422, f"uri {uri} should be rejected"


def test_asr_job_rejects_remote_host(client: TestClient, auth_header: dict[str, str]) -> None:
    """A `file://host/...` URI with a non-localhost authority is rejected.

    The OpenAPI ECMA pattern already excludes this (`file:///` requires the
    triple-slash form), but we check the gateway re-rejects so a future
    contract relaxation cannot silently expose remote-mount injection.
    """
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(input_uri="file://attacker.example.com/data/outputs/x.wav"),
    )
    assert r.status_code == 422


def test_asr_job_rejects_oversized_input_uri(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    long_path = "a" * 5_000
    r = client.post(
        "/v1/audio/asr/jobs",
        headers=auth_header,
        json=_asr_request(input_uri=f"file:///data/outputs/{long_path}.wav"),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Contract parity — keep api-contract.yaml in lockstep
# ---------------------------------------------------------------------------


def test_contract_tts_request_enum_matches_route() -> None:
    """OpenAPI TtsJobRequest.model.enum must match the FastAPI Literal."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    enum = contract["components"]["schemas"]["TtsJobRequest"]["properties"]["model"]["enum"]
    assert sorted(enum) == sorted(["qwen3-tts", "voxcpm2"])


def test_contract_asr_request_enum_matches_route() -> None:
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    enum = contract["components"]["schemas"]["AsrJobRequest"]["properties"]["model"]["enum"]
    assert enum == ["qwen3-asr"]


def test_contract_audio_routes_advertise_503() -> None:
    """A misconfigured jobs_dir yields a stable 503 envelope; the contract
    must list it so generated clients backoff instead of treating the
    response as an unknown failure (parity with media routes)."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    for path in ("/v1/audio/tts/jobs", "/v1/audio/asr/jobs"):
        responses = contract["paths"][path]["post"]["responses"]
        assert "503" in responses, f"{path} missing 503 in contract"


def test_contract_audio_requests_forbid_extra_fields() -> None:
    """Both audio request schemas must set additionalProperties=false so
    the OpenAPI shape matches the gateway's strict Pydantic model."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    for schema in ("TtsJobRequest", "AsrJobRequest"):
        s = contract["components"]["schemas"][schema]
        assert (
            s.get("additionalProperties") is False
        ), f"{schema}.additionalProperties must be false"


def test_contract_job_accepted_status_includes_audio_types() -> None:
    """The shared JobAccepted envelope must include both tts and asr in
    its `type` enum so audio submissions return a contract-compliant body."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    accepted = contract["components"]["schemas"]["JobAccepted"]
    type_enum = accepted["properties"]["type"]["enum"]
    assert "tts" in type_enum
    assert "asr" in type_enum


# ---------------------------------------------------------------------------
# Jobs-dir misconfiguration — read-only host, no bind mount
# ---------------------------------------------------------------------------


def test_tts_job_returns_503_when_jobs_dir_unwritable(
    client: TestClient, auth_header: dict[str, str], tmp_path: Path
) -> None:
    """Mirrors the deployed read-only container with no jobs volume mount:
    submission returns 503 with a clean envelope instead of a 500."""
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        from sparky_gateway.job_store import JobStore

        client.app.state.job_store = JobStore(parent / "jobs")
        r = client.post("/v1/audio/tts/jobs", headers=auth_header, json=_tts_request())
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "jobs_dir_unavailable"
        assert "ro/jobs" not in r.json()["error"]["message"]
    finally:
        parent.chmod(0o700)


def test_asr_job_returns_503_when_jobs_dir_unwritable(
    client: TestClient, auth_header: dict[str, str], tmp_path: Path
) -> None:
    parent = tmp_path / "ro"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        from sparky_gateway.job_store import JobStore

        client.app.state.job_store = JobStore(parent / "jobs")
        r = client.post("/v1/audio/asr/jobs", headers=auth_header, json=_asr_request())
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "jobs_dir_unavailable"
        assert "ro/jobs" not in r.json()["error"]["message"]
    finally:
        parent.chmod(0o700)
