"""Shared pytest fixtures.

Tests construct a fresh `Settings` with a known API key and point at the
canonical `config/model-registry.yaml` so the registry shape stays in
lockstep with the committed file.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sparky_gateway.config import Settings
from sparky_gateway.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "config" / "model-registry.yaml"
TEST_API_KEY = "test-key-not-for-production-use-only"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # Pre-create the jobs ledger so /ready stays green for happy-path tests;
    # individual tests that exercise the unwritable path (PLAN §10 read-only
    # rootfs / missing bind mount) override this in-test.
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    return Settings(
        sparky_api_key=TEST_API_KEY,
        sparky_log_level="warning",
        sparky_model_registry_path=REGISTRY_PATH,
        sparky_logging_config_path=None,
        jobs_dir=jobs_dir,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def client_registry_no_active(tmp_path: Path) -> Iterator[TestClient]:
    """Registry YAML with zero active models — `/ready` must stay not_ready."""
    reg_path = tmp_path / "registry.yaml"
    reg_path.write_text(
        """version: 1
models:
  - id: inactive-only
    family: text
    role: premium-text
    runtime: vllm
    active: false
"""
    )
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    settings = Settings(
        sparky_api_key=TEST_API_KEY,
        sparky_log_level="warning",
        sparky_model_registry_path=reg_path,
        sparky_logging_config_path=None,
        jobs_dir=jobs_dir,
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c
