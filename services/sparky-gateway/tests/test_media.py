"""POST /v1/media/{image,video}/jobs — submission validation + enqueue (PLAN §16, §18)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
API_CONTRACT_PATH = REPO_ROOT / "config" / "api-contract.yaml"


def _video_request(**overrides: Any) -> dict[str, Any]:
    """Build a contract-aligned video request with derived frame budget."""
    base: dict[str, Any] = {
        "model": "ltx-2",
        "prompt": "a serene lake at dawn",
        "duration_seconds": 5,
        "fps": 24,
        "width": 1280,
        "height": 720,
    }
    base.update(overrides)
    frames = math.ceil(base["duration_seconds"] * base["fps"])
    base.setdefault("max_frames", frames)
    base.setdefault("max_pixel_frames", frames * base["width"] * base["height"])
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_image_jobs_require_auth(client: TestClient) -> None:
    r = client.post("/v1/media/image/jobs", json={"model": "flux2-dev", "prompt": "x"})
    assert r.status_code == 401


def test_video_jobs_require_auth(client: TestClient) -> None:
    r = client.post("/v1/media/video/jobs", json=_video_request())
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Image — happy path + registry / schema gates
# ---------------------------------------------------------------------------


def test_image_job_happy_path_returns_202(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "a small cat in a sunlit kitchen"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["type"] == "image"
    assert body["status"] == "queued"
    UUID(body["job_id"])  # must parse as a UUID


def test_image_job_accepts_each_approved_model(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    for model in ("flux2-dev", "flux2-klein", "qwen-image", "hunyuanimage-3-instruct"):
        r = client.post(
            "/v1/media/image/jobs",
            headers=auth_header,
            json={"model": model, "prompt": "x"},
        )
        assert r.status_code == 202, f"{model} should be accepted: {r.json()}"


def test_image_jobs_endpoint_rejects_video_model(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """Submitting a video model to /v1/media/image/jobs is a route mismatch."""
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "ltx-2", "prompt": "x"},
    )
    assert r.status_code == 422


def test_image_job_persists_record_on_disk(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x"},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    jobs_dir = Path(client.app.state.settings.jobs_dir)
    on_disk = json.loads((jobs_dir / f"{job_id}.json").read_text())
    assert on_disk["status"] == "queued"
    assert on_disk["model"] == "flux2-dev"
    assert on_disk["request"]["prompt"] == "x"


def test_image_job_rejects_text_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "nemotron-3-super-120b-a12b-nvfp4", "prompt": "x"},
    )
    assert r.status_code == 422
    # Pydantic enum mismatch fires before the registry check, so we accept
    # either error code; what matters is the contract rejection.
    assert r.json()["error"]["code"] in ("invalid_request", "invalid_model_for_route")


def test_image_job_rejects_excluded_model(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux.1-dev", "prompt": "x"},
    )
    assert r.status_code == 422


def test_image_job_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x", "scheduler": "dpm++"},
    )
    assert r.status_code == 422


def test_image_job_requires_prompt(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post("/v1/media/image/jobs", headers=auth_header, json={"model": "flux2-dev"})
    assert r.status_code == 422


def test_image_job_requires_aligned_dimensions(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x", "width": 1023, "height": 1024},
    )
    assert r.status_code == 422


def test_image_job_rejects_oversized_dimensions(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x", "width": 8192, "height": 1024},
    )
    assert r.status_code == 422


def test_image_job_rejects_oversized_steps(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x", "steps": 9999},
    )
    assert r.status_code == 422


def test_image_job_rejects_negative_seed(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x", "seed": -1},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Video — happy path + envelope cross-checks
# ---------------------------------------------------------------------------


def test_video_job_happy_path_returns_202(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/media/video/jobs",
        headers=auth_header,
        json=_video_request(),
    )
    assert r.status_code == 202
    body = r.json()
    assert body["type"] == "video"
    assert body["status"] == "queued"
    UUID(body["job_id"])


def test_video_job_rejects_image_model(client: TestClient, auth_header: dict[str, str]) -> None:
    payload = _video_request()
    payload["model"] = "flux2-dev"
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_video_job_rejects_max_frames_mismatch(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    """ceil(duration × fps) === max_frames is a Phase-1 hard contract (PLAN §16)."""
    payload = _video_request()
    payload["max_frames"] = payload["max_frames"] + 1
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_video_job_rejects_max_pixel_frames_mismatch(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    payload = _video_request()
    payload["max_pixel_frames"] = payload["max_pixel_frames"] - 1
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_video_job_rejects_alignment_violation(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    payload = _video_request(width=1273)  # 1273 not multipleOf 16
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_video_job_rejects_duration_over_cap(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    payload = _video_request(duration_seconds=99)
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


def test_video_job_rejects_extra_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    payload = _video_request()
    payload["scheduler"] = "dpm++"
    r = client.post("/v1/media/video/jobs", headers=auth_header, json=payload)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Contract parity — keep api-contract.yaml in lockstep
# ---------------------------------------------------------------------------


def test_contract_image_request_enum_matches_route() -> None:
    """OpenAPI ImageJobRequest.model.enum must match the FastAPI Literal."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    enum = contract["components"]["schemas"]["ImageJobRequest"]["properties"]["model"]["enum"]
    assert sorted(enum) == sorted(
        ["flux2-dev", "flux2-klein", "qwen-image", "hunyuanimage-3-instruct"]
    )


def test_contract_video_request_enum_matches_route() -> None:
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    enum = contract["components"]["schemas"]["VideoJobRequest"]["properties"]["model"]["enum"]
    assert sorted(enum) == sorted(["ltx-2", "wan-2.2", "hunyuanvideo-1.5"])


def test_contract_job_accepted_status_is_queued_only() -> None:
    """JobAccepted.status must be a single-value enum so callers branch
    correctly between 202 (queued) and a later GET /v1/jobs/{id}."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    accepted = contract["components"]["schemas"]["JobAccepted"]
    assert accepted["properties"]["status"]["enum"] == ["queued"]
