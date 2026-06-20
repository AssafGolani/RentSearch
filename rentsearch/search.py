"""Search orchestration: query sources -> filter -> de-dupe -> persist 'seen'.

This module is the heart of the system and is deliberately UI-agnostic: it knows
nothing about Telegram. It returns the list of *new* (previously unseen)
listings so the caller can decide how to present them.
"""
from __future__ import annotations

import logging

from .dedup import deduplicate
from .models import SavedFilter, SeenProperty
from .sources import all_sources, get_source
from .sources.base import Listing, SearchFilter

logger = logging.getLogger(__name__)


def run_search(flt: SearchFilter, limit_per_source: int = 40) -> list[Listing]:
    """Query every selected source, filter and de-duplicate the results.

    Returns the merged, de-duplicated list of listings that satisfy ``flt``.
    Does not touch the database (no 'seen' bookkeeping) - that's the caller's
    job via :func:`collect_new_listings`.
    """
    selected = _selected_sources(flt)
    raw: list[Listing] = []
    for source in selected:
        try:
            results = source.search(flt, limit=limit_per_source)
            logger.info("Source %s returned %d raw listings", source.name, len(results))
            raw.extend(results)
        except Exception as exc:
            logger.warning("Source %s failed: %s", source.name, exc)

    # Apply the filter again locally (sources only do best-effort server filtering)
    # and enforce the global "must have image + price" guarantees.
    filtered = [l for l in raw if flt.matches(l)]
    deduped = deduplicate(filtered)
    # Most recently fetched / cheapest first is a reasonable default ordering.
    deduped.sort(key=lambda l: (l.price if l.has_price else 10**9))
    return deduped


def collect_new_listings(saved: SavedFilter, session) -> list[Listing]:
    """Run a saved filter and return only the listings not seen before.

    Records every newly surfaced listing in ``seen_properties`` (keyed by both
    its global id and its cross-source fingerprint) so it is never reported
    twice - even if it later appears on a different source.
    """
    flt = saved.to_search_filter()
    listings = run_search(flt)

    seen_globals, seen_fps = _load_seen(session, saved.chat_id)
    new_listings: list[Listing] = []
    for listing in listings:
        gid = listing.global_id
        fp = listing.fingerprint()
        if gid in seen_globals or fp in seen_fps:
            continue
        new_listings.append(listing)
        seen_globals.add(gid)
        seen_fps.add(fp)
        session.add(
            SeenProperty(
                chat_id=saved.chat_id,
                filter_id=saved.id,
                global_id=gid,
                fingerprint=fp,
                source=listing.source,
                url=listing.url,
                title=listing.title,
                price=listing.price,
            )
        )
    logger.info("Filter '%s': %d new listings", saved.name, len(new_listings))
    return new_listings


def _selected_sources(flt: SearchFilter):
    if flt.sources:
        chosen = [get_source(name) for name in flt.sources]
        return [s for s in chosen if s is not None]
    return all_sources()


def _load_seen(session, chat_id: int) -> tuple[set[str], set[str]]:
    rows = session.query(SeenProperty.global_id, SeenProperty.fingerprint).filter(
        SeenProperty.chat_id == chat_id
    ).all()
    globals_ = {r[0] for r in rows}
    fps = {r[1] for r in rows}
    return globals_, fps
