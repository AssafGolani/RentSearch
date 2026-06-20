"""Cross-source de-duplication.

The same physical apartment is frequently posted on Yad2, Madlan, a Facebook
group and an agency site at once. We collapse those into a single listing so the
user is notified once.

Two layers of matching:

1. **Exact fingerprint** (:meth:`Listing.fingerprint`) - normalized address +
   rooms + size + price bucket. Cheap and catches the common case.
2. **Fuzzy fallback** - for listings that lack a clean address, compare title +
   price + rooms with token-set similarity (rapidfuzz). This catches re-posts
   with slightly different wording.

When duplicates are found we keep the "best" copy: the one with the most images,
then the one with coordinates, then the cheapest price.
"""
from __future__ import annotations

import logging

from rapidfuzz import fuzz

from .sources.base import Listing, _normalize_text

logger = logging.getLogger(__name__)

# Listings are considered the same when their title similarity is at/above this
# and price + rooms line up.
FUZZY_TITLE_THRESHOLD = 88
PRICE_TOLERANCE = 150  # ₪


def _quality_key(listing: Listing) -> tuple:
    """Higher is better. Used to pick which duplicate to keep."""
    return (
        len(listing.images),
        1 if (listing.lat is not None and listing.lon is not None) else 0,
        1 if listing.description else 0,
        -(listing.price or 10**9),  # prefer cheaper when all else equal
    )


def _is_fuzzy_duplicate(a: Listing, b: Listing) -> bool:
    if a.rooms is not None and b.rooms is not None and abs(a.rooms - b.rooms) > 0.5:
        return False
    if a.has_price and b.has_price and abs(a.price - b.price) > PRICE_TOLERANCE:
        return False
    title_a = _normalize_text(a.title)
    title_b = _normalize_text(b.title)
    if not title_a or not title_b:
        return False
    score = fuzz.token_set_ratio(title_a, title_b)
    return score >= FUZZY_TITLE_THRESHOLD


def deduplicate(listings: list[Listing]) -> list[Listing]:
    """Collapse duplicate listings, keeping the best copy of each."""
    # Pass 1: bucket by exact fingerprint.
    by_fp: dict[str, Listing] = {}
    leftovers: list[Listing] = []
    for listing in listings:
        fp = listing.fingerprint()
        # A fingerprint built mostly from "?" placeholders isn't reliable.
        if fp_is_weak(listing):
            leftovers.append(listing)
            continue
        existing = by_fp.get(fp)
        if existing is None or _quality_key(listing) > _quality_key(existing):
            by_fp[fp] = listing

    kept = list(by_fp.values())

    # Pass 2: fuzzy-merge the weak-fingerprint leftovers against what we kept.
    for cand in leftovers:
        merged = False
        for i, existing in enumerate(kept):
            if _is_fuzzy_duplicate(cand, existing):
                if _quality_key(cand) > _quality_key(existing):
                    kept[i] = cand
                merged = True
                break
        if not merged:
            kept.append(cand)

    removed = len(listings) - len(kept)
    if removed:
        logger.info("De-dup: %d -> %d listings (%d duplicates removed)", len(listings), len(kept), removed)
    return kept


def fp_is_weak(listing: Listing) -> bool:
    """True when a listing lacks enough identity signal for fingerprint matching."""
    has_addr = bool(_normalize_text(listing.full_address))
    return not (has_addr and (listing.has_price or listing.size_sqm))
