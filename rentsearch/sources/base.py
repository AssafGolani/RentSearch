"""Core abstractions shared by every property source adapter.

A *source* (Yad2, Madlan, Facebook, a generic Israeli real-estate site, ...)
knows how to take a normalized :class:`SearchFilter` and return a list of
normalized :class:`Listing` objects. The rest of the system (de-duplication,
persistence, Telegram notification) only ever deals with :class:`Listing`,
never with the raw HTML/JSON of any particular site.
"""
from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Hebrew keyword dictionaries used both for filtering and feature detection.
# --------------------------------------------------------------------------- #

# ממ"ד = protected/reinforced room inside the apartment.
MAMAD_KEYWORDS = [
    'ממ"ד', "ממ״ד", "ממד", "ממ''ד", "mamad", "saferoom", "safe room",
    "חדר ממוגן", "חדר מוגן",
]
# מקלט = (building/neighborhood) bomb shelter.
SHELTER_KEYWORDS = [
    "מקלט", "מרחב מוגן", "miklat", "shelter", "bomb shelter",
]

CURRENCY_SYMBOLS = {"₪": "ILS", "$": "USD", "€": "EUR"}


def _contains_any(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k.lower() in low for k in keywords)


@dataclass
class Listing:
    """A single rental property, normalized across all sources."""

    source: str
    source_id: str
    url: str
    title: str = ""
    description: str = ""

    price: int | None = None
    currency: str = "ILS"

    rooms: float | None = None
    size_sqm: int | None = None
    floor: int | None = None

    city: str = ""
    neighborhood: str = ""
    street: str = ""
    address: str = ""

    lat: float | None = None
    lon: float | None = None

    images: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)

    has_mamad: bool = False
    has_shelter: bool = False

    posted_at: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        # Auto-detect ממ"ד / מקלט from any free-text we have, if not set explicitly.
        haystack = " ".join(filter(None, [self.title, self.description, " ".join(self.features)]))
        if not self.has_mamad:
            self.has_mamad = _contains_any(haystack, MAMAD_KEYWORDS)
        if not self.has_shelter:
            self.has_shelter = _contains_any(haystack, SHELTER_KEYWORDS)

    # -- derived helpers ---------------------------------------------------- #

    @property
    def has_image(self) -> bool:
        return bool(self.images)

    @property
    def has_price(self) -> bool:
        return self.price is not None and self.price > 0

    @property
    def full_address(self) -> str:
        parts = [p for p in (self.street, self.neighborhood, self.city) if p]
        return ", ".join(dict.fromkeys(parts))  # de-dupe while preserving order

    @property
    def global_id(self) -> str:
        """Stable per-source identifier (source + source_id)."""
        return f"{self.source}:{self.source_id}"

    def google_maps_url(self) -> str:
        """A Google Maps link that pinpoints the property."""
        if self.lat is not None and self.lon is not None:
            return f"https://www.google.com/maps/search/?api=1&query={self.lat},{self.lon}"
        query = self.full_address or self.title
        from urllib.parse import quote_plus

        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query + ', Israel')}"

    def fingerprint(self) -> str:
        """Content fingerprint used to detect the *same* property across sources.

        Built from the strongest identity signals (normalized address, rooms,
        size, price bucket). Two listings with the same fingerprint are treated
        as duplicates regardless of which site they came from.
        """
        addr = _normalize_text(self.full_address)
        rooms = f"{self.rooms:.1f}" if self.rooms is not None else "?"
        size = str(self.size_sqm or "?")
        # Bucket price to the nearest 100 so small differences still collide.
        price_bucket = str(round(self.price / 100) * 100) if self.has_price else "?"
        raw = f"{addr}|{rooms}|{size}|{price_bucket}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation/diacritics-ish, collapse whitespace."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[\"'`,.;:!?()\[\]{}/\\\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class SearchFilter:
    """Normalized, source-agnostic set of search criteria.

    This mirrors the persisted ``Filter`` model but is a plain value object so
    adapters and tests don't need a database session.
    """

    name: str = "filter"

    city: str = ""
    neighborhoods: list[str] = field(default_factory=list)
    property_type: str = ""  # apartment / house / unit / ...

    min_price: int | None = None
    max_price: int | None = None
    min_rooms: float | None = None
    max_rooms: float | None = None
    min_size: int | None = None
    max_size: int | None = None
    min_floor: int | None = None
    max_floor: int | None = None

    require_mamad: bool = False
    require_shelter: bool = False
    require_elevator: bool = False
    require_parking: bool = False
    require_balcony: bool = False
    pets_allowed: bool = False

    # Per the product spec these default to True: only ever surface listings
    # that have at least one image and a stated price.
    require_image: bool = True
    require_price: bool = True

    sources: list[str] = field(default_factory=list)  # empty == all enabled sources

    def matches(self, listing: Listing) -> bool:
        """Return True if ``listing`` satisfies every constraint in this filter."""
        if self.require_image and not listing.has_image:
            return False
        if self.require_price and not listing.has_price:
            return False

        if self.min_price is not None and (listing.price or 0) < self.min_price:
            return False
        if self.max_price is not None and listing.price is not None and listing.price > self.max_price:
            return False

        if self.min_rooms is not None and (listing.rooms or 0) < self.min_rooms:
            return False
        if self.max_rooms is not None and listing.rooms is not None and listing.rooms > self.max_rooms:
            return False

        if self.min_size is not None and (listing.size_sqm or 0) < self.min_size:
            return False
        if self.max_size is not None and listing.size_sqm is not None and listing.size_sqm > self.max_size:
            return False

        if self.min_floor is not None and listing.floor is not None and listing.floor < self.min_floor:
            return False
        if self.max_floor is not None and listing.floor is not None and listing.floor > self.max_floor:
            return False

        if self.require_mamad and not listing.has_mamad:
            return False
        if self.require_shelter and not listing.has_shelter:
            return False

        if self.city:
            want = _normalize_text(self.city)
            have = _normalize_text(f"{listing.city} {listing.address} {listing.full_address}")
            if want and want not in have:
                return False

        if self.neighborhoods:
            have = _normalize_text(f"{listing.neighborhood} {listing.address}")
            if not any(_normalize_text(n) in have for n in self.neighborhoods):
                return False

        return True


class SourceAdapter(ABC):
    """Base class every property source must implement."""

    #: short stable id, e.g. "yad2" - also used in Listing.source
    name: str = "base"
    #: human label for UI
    label: str = "Base"
    #: set False for adapters that require credentials/manual setup
    enabled_by_default: bool = True

    @abstractmethod
    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        """Return up to ``limit`` listings matching ``flt``.

        Implementations should be defensive: a failure to reach the source must
        raise (so the orchestrator can log it) but must never return partial
        garbage. The orchestrator applies ``flt.matches`` again afterwards, so
        adapters only need *best-effort* server-side filtering.
        """
        raise NotImplementedError
