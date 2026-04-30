"""Runtime settings for sparky-gateway — see PLAN.md §7.4 (env keys) and §10."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration.

    Field names mirror env vars (case-insensitive). Real env file lives at
    `/etc/sparky/sparky.env` per PLAN §10 — never a tracked .env.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        env_file=None,
    )

    sparky_api_key: str = ""
    sparky_gateway_bind: str = "0.0.0.0:8080"
    sparky_log_level: str = "info"
    sparky_request_timeout_seconds: int = 120

    nemotron_vllm_url: str = "http://127.0.0.1:8000"
    nemotron_trtllm_url: str = "http://127.0.0.1:8001"
    comfyui_url: str = "http://127.0.0.1:8188"
    audio_service_url: str = "http://127.0.0.1:9001"

    sparky_model_registry_path: Path = Path("/opt/sparky/config/model-registry.yaml")
    sparky_logging_config_path: Path | None = None
