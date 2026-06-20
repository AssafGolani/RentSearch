"""Load optional generic-source definitions from config.yaml."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .config import BASE_DIR
from .sources import register_generic_sources

logger = logging.getLogger(__name__)


def load_generic_sources(path: Path | None = None) -> None:
    """Read config.yaml (if present) and register any generic_sources."""
    config_path = path or (BASE_DIR / "config.yaml")
    if not config_path.exists():
        logger.info("No config.yaml found; using built-in sources only.")
        return
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s", config_path, exc)
        return
    register_generic_sources(data.get("generic_sources", []))
