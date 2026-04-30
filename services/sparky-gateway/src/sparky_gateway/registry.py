"""Model registry loader — see PLAN.md §3 (matrix), §7.3 (schema), §4.3 (co-residency)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    family: Literal["text", "image", "video", "audio"]
    role: str
    tier: Literal["A", "B", "C"] | None = None
    runtime: Literal["vllm", "trtllm", "comfyui", "audio"]
    runtime_url: str | None = None
    revision: str | None = None
    priority: Literal["P0", "P1", "P2"] | None = None
    active: bool = True
    co_resident: bool | None = None
    eviction_idle_minutes: int | None = None


class CoResidency(BaseModel):
    vram_headroom_gb: int = 8
    default_eviction_idle_minutes: int = 15


class Defaults(BaseModel):
    weights_root: str = "/data/models"
    cache_root: str = "/data/cache"
    outputs_root: str = "/data/outputs"


class Registry(BaseModel):
    version: int
    defaults: Defaults = Defaults()
    co_residency: CoResidency = CoResidency()
    models: list[Model]
    excluded_models: list[str] = []

    def active(self) -> list[Model]:
        return [m for m in self.models if m.active]

    def by_id(self, model_id: str) -> Model | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None


def load_registry(path: Path) -> Registry:
    """Load and validate the YAML registry. Raises on schema errors."""
    raw: Any = yaml.safe_load(path.read_text())
    return Registry.model_validate(raw)
