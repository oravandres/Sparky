"""Logging bootstrap — uses `config/logging.yaml` when present (PLAN.md §19)."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

import yaml


def setup_logging(config_path: Path | None, level: str) -> None:
    """Load dictConfig from a YAML file or fall back to a basic configuration.

    The YAML pulls `sparky_common.logging_filters.RedactSecretsFilter` into the
    handler chain so `*_KEY`, `*_TOKEN`, `*_SECRET` and Bearer values are
    stripped before structured logs leave the process (PLAN §10).
    """
    if config_path is not None and config_path.exists():
        cfg: Any = yaml.safe_load(config_path.read_text())
        logging.config.dictConfig(cfg)
        return

    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
