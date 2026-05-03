"""Runtime settings for sparky-gateway — see PLAN.md §7.4 (env keys) and §10."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
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
    # Chat proxy — policy limits (PLAN §12, bounded generation in api-contract.yaml).
    sparky_chat_max_messages: int = Field(default=64, ge=1, le=128)
    sparky_chat_max_content_chars: int = Field(default=120_000, ge=1024, le=1_000_000)
    sparky_nemotron_max_inflight: int = Field(default=2, ge=1, le=64)
    sparky_max_request_body_bytes: int = Field(default=2_097_152, ge=64, le=16_777_216)
    sparky_reasoning_model_id: str = "nemotron-3-super-120b-a12b-nvfp4"
    sparky_reasoning_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    sparky_reasoning_compare_max_tokens: int = Field(default=4096, ge=256, le=16384)
    # Agentic RAG — Nemotron-backed stages share the reasoning model by default (PLAN §6, §14).
    sparky_agentic_rag_model_id: str = "nemotron-3-super-120b-a12b-nvfp4"
    sparky_agentic_rag_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    sparky_agentic_rag_plan_max_tokens: int = Field(default=2048, ge=256, le=16384)
    sparky_agentic_rag_evaluate_max_tokens: int = Field(default=2048, ge=256, le=16384)
    sparky_agentic_rag_synthesize_max_tokens: int = Field(default=4096, ge=256, le=16384)
    sparky_agentic_rag_verify_max_tokens: int = Field(default=2048, ge=256, le=16384)
    sparky_agentic_rag_finalize_max_tokens: int = Field(default=4096, ge=256, le=16384)
    # Coding intelligence — Nemotron-backed code review / architecture / refactor-plan /
    # security-review (PLAN §5.4, §15). All four routes share one tunable ceiling; bump via
    # config rather than per-route env vars so operators have a single dial.
    sparky_coding_model_id: str = "nemotron-3-super-120b-a12b-nvfp4"
    sparky_coding_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    sparky_coding_max_tokens: int = Field(default=4096, ge=256, le=16384)

    nemotron_vllm_url: str = "http://127.0.0.1:8000"
    nemotron_trtllm_url: str = "http://127.0.0.1:8001"
    comfyui_url: str = "http://127.0.0.1:8188"
    audio_service_url: str = "http://127.0.0.1:9001"

    sparky_model_registry_path: Path = Path("/opt/sparky/config/model-registry.yaml")
    sparky_logging_config_path: Path | None = None
    # File-backed async job ledger (PLAN §18). Env var ``JOBS_DIR`` matches the
    # PLAN §7.4 / §8 convention shared with MODELS_DIR / OUTPUTS_DIR; tests
    # override via ``jobs_dir=...`` so they never write to /var.
    jobs_dir: Path = Path("/var/lib/sparky/jobs")

    # Dev-only: exposes /docs, /redoc, /openapi.json (otherwise omitted — PLAN §12 auth surface).
    sparky_enable_openapi_docs: bool = False
