"""Source adapter registry.

The registry maps a stable source name -> a :class:`SourceAdapter` instance.
Built-in sources are always registered; extra "generic" JSON-LD sites are added
from ``config.yaml`` at startup via :func:`register_generic_sources`.
"""
from __future__ import annotations

import logging

from .base import Listing, SearchFilter, SourceAdapter
from .facebook import FacebookSource
from .generic import GenericSource
from .madlan import MadlanSource
from .yad2 import Yad2Source

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter: SourceAdapter) -> None:
    _REGISTRY[adapter.name] = adapter


def get_source(name: str) -> SourceAdapter | None:
    return _REGISTRY.get(name)


def all_sources() -> list[SourceAdapter]:
    return list(_REGISTRY.values())


def enabled_source_names() -> list[str]:
    return [a.name for a in _REGISTRY.values()]


def register_builtin_sources() -> None:
    register(Yad2Source())
    register(MadlanSource())
    register(FacebookSource())


def register_generic_sources(configs: list[dict]) -> None:
    """Register extra JSON-LD sites from config.

    Each config dict: {name, label, search_url}.
    """
    for cfg in configs or []:
        try:
            register(
                GenericSource(
                    name=cfg["name"],
                    label=cfg.get("label", cfg["name"]),
                    search_url_template=cfg["search_url"],
                )
            )
            logger.info("Registered generic source: %s", cfg["name"])
        except KeyError as exc:
            logger.warning("Skipping malformed generic source config (missing %s): %s", exc, cfg)


# Register built-ins on import so callers always have Yad2/Madlan/Facebook.
register_builtin_sources()

__all__ = [
    "Listing",
    "SearchFilter",
    "SourceAdapter",
    "register",
    "get_source",
    "all_sources",
    "enabled_source_names",
    "register_builtin_sources",
    "register_generic_sources",
]
