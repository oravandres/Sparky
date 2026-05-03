"""GET /v1/jobs/{id} + POST /v1/jobs/{id}/cancel — shared job control (PLAN §5.7, §18)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
API_CONTRACT_PATH = REPO_ROOT / "config" / "api-contract.yaml"


def _submit_image(client: TestClient, auth_header: dict[str, str]) -> str:
    r = client.post(
        "/v1/media/image/jobs",
        headers=auth_header,
        json={"model": "flux2-dev", "prompt": "x"},
    )
    assert r.status_code == 202
    return str(r.json()["job_id"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_get_job_requires_auth(client: TestClient) -> None:
    r = client.get("/v1/jobs/11111111-1111-4111-8111-111111111111")
    assert r.status_code == 401


def test_cancel_job_requires_auth(client: TestClient) -> None:
    r = client.post("/v1/jobs/11111111-1111-4111-8111-111111111111/cancel")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET — happy + 404 paths
# ---------------------------------------------------------------------------


def test_get_job_returns_full_record(client: TestClient, auth_header: dict[str, str]) -> None:
    job_id = _submit_image(client, auth_header)
    r = client.get(f"/v1/jobs/{job_id}", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["type"] == "image"
    assert body["model"] == "flux2-dev"
    assert body["status"] == "queued"
    assert "created_at" in body
    # Internal fields must not leak.
    assert "request" not in body


def test_get_job_unknown_returns_404(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get(
        "/v1/jobs/22222222-2222-4222-8222-222222222222",
        headers=auth_header,
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_get_job_invalid_uuid_returns_404(client: TestClient, auth_header: dict[str, str]) -> None:
    """The handler must refuse to interpret a non-uuid path segment as an
    on-disk lookup; it returns 404 (not 500 / not 422)."""
    r = client.get("/v1/jobs/../etc/passwd", headers=auth_header)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Cancel — state transitions
# ---------------------------------------------------------------------------


def test_cancel_queued_job_returns_cancelled(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    job_id = _submit_image(client, auth_header)
    r = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["completed_at"] is not None


def test_cancel_unknown_returns_404(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post(
        "/v1/jobs/22222222-2222-4222-8222-222222222222/cancel",
        headers=auth_header,
    )
    assert r.status_code == 404


def test_cancel_invalid_uuid_returns_404(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.post("/v1/jobs/not-a-uuid/cancel", headers=auth_header)
    assert r.status_code == 404


def test_cancel_already_cancelled_is_idempotent(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    job_id = _submit_image(client, auth_header)
    first = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth_header)
    second = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth_header)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "cancelled"


def test_cancel_completed_job_returns_409(client: TestClient, auth_header: dict[str, str]) -> None:
    job_id = _submit_image(client, auth_header)
    jobs_dir = Path(client.app.state.settings.jobs_dir)
    record_path = jobs_dir / f"{job_id}.json"
    record = json.loads(record_path.read_text())
    record["status"] = "completed"
    record["completed_at"] = "2026-04-30T12:00:00Z"
    record["output_uri"] = "file:///data/outputs/images/done.png"
    record_path.write_text(json.dumps(record, sort_keys=True))

    r = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth_header)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "job_terminal"


def test_cancel_failed_job_returns_409(client: TestClient, auth_header: dict[str, str]) -> None:
    job_id = _submit_image(client, auth_header)
    jobs_dir = Path(client.app.state.settings.jobs_dir)
    record_path = jobs_dir / f"{job_id}.json"
    record = json.loads(record_path.read_text())
    record["status"] = "failed"
    record["error"] = "upstream timeout"
    record_path.write_text(json.dumps(record, sort_keys=True))

    r = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth_header)
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Contract parity — keep api-contract.yaml in lockstep with FastAPI handlers
# ---------------------------------------------------------------------------


def test_contract_jobs_routes_advertise_auth_and_terminal_responses() -> None:
    """``config/api-contract.yaml`` must list every status code the
    handlers can return for the shared job-control endpoints. Generated
    clients use this list to decide what they retry vs surface."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())

    get_responses = contract["paths"]["/v1/jobs/{job_id}"]["get"]["responses"]
    assert "200" in get_responses
    assert "401" in get_responses, "GET /v1/jobs/{job_id} missing 401 in contract"
    assert "404" in get_responses

    cancel_responses = contract["paths"]["/v1/jobs/{job_id}/cancel"]["post"]["responses"]
    assert "200" in cancel_responses
    assert "401" in cancel_responses, "cancel missing 401 in contract"
    assert "404" in cancel_responses
    assert "409" in cancel_responses, "cancel missing 409 (job_terminal) in contract"


def test_contract_defines_conflict_response_component() -> None:
    """``components.responses.Conflict`` must exist so the cancel route's
    409 reference resolves; the description must mention the terminal-state
    rule so contract readers know when to expect it."""
    contract = yaml.safe_load(API_CONTRACT_PATH.read_text())
    conflict = contract["components"]["responses"]["Conflict"]
    assert "terminal" in conflict["description"].lower()
    assert conflict["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/Error"
