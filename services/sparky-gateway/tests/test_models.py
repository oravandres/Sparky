"""GET /v1/models — model registry shape (PLAN §5.1, §7.3, §3)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_models_returns_active_set(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get("/v1/models", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0


def test_models_include_required_fields(client: TestClient, auth_header: dict[str, str]) -> None:
    r = client.get("/v1/models", headers=auth_header)
    body = r.json()
    for model in body["data"]:
        for field in ("id", "family", "role", "runtime", "active", "state"):
            assert field in model, f"missing {field} in model {model}"
        assert model["active"] is True
        assert model["state"] in {"hot", "cold", "loading", "evicting"}
        assert model["family"] in {"text", "image", "video", "audio"}
        assert model["runtime"] in {"vllm", "trtllm", "comfyui", "audio"}


def test_models_contain_premium_text_p0(client: TestClient, auth_header: dict[str, str]) -> None:
    """Nemotron 3 Super is the always-hot Tier A entry (PLAN §4.3)."""
    r = client.get("/v1/models", headers=auth_header)
    ids = [m["id"] for m in r.json()["data"]]
    assert "nemotron-3-super-120b-a12b-nvfp4" in ids
