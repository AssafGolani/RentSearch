"""Madlan source adapter.

Madlan (madlan.co.il) is a Next.js application. Its listing pages embed a
``__NEXT_DATA__`` JSON blob that contains the structured poi/listing data. We
fetch the rentals search page for the requested city and parse that blob.

As with Yad2, the parser is defensive against schema drift.
"""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

from bs4 import BeautifulSoup

from .base import Listing, SearchFilter, SourceAdapter
from .http import make_client

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.madlan.co.il/for-rent/{city}-ישראל"
ITEM_BASE = "https://www.madlan.co.il/listings"


class MadlanSource(SourceAdapter):
    name = "madlan"
    label = "Madlan"

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        city = flt.city or "תל-אביב-יפו"
        url = SEARCH_URL.format(city=quote(city.replace(" ", "-")))
        with make_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        data = self._extract_next_data(html)
        items = self._find_listings(data)
        listings: list[Listing] = []
        for item in items:
            try:
                listing = self._parse_item(item)
            except Exception as exc:
                logger.debug("Madlan: skipping unparseable item: %s", exc)
                continue
            if listing is not None:
                listings.append(listing)
        logger.info("Madlan: parsed %d listings", len(listings))
        return listings[:limit]

    # ------------------------------------------------------------------ #

    def _extract_next_data(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if tag and tag.string:
            try:
                return json.loads(tag.string)
            except json.JSONDecodeError:
                pass
        # Fallback: regex any inline JSON that looks like an apollo/state cache.
        m = re.search(r'__NEXT_DATA__\s*=\s*({.*?})\s*</script>', html, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return {}

    def _find_listings(self, data: dict) -> list[dict]:
        """Walk the nested Next/Apollo cache and collect listing-shaped dicts."""
        found: list[dict] = []

        def looks_like_listing(d: dict) -> bool:
            keys = set(d.keys())
            return ("id" in keys or "poiId" in keys) and (
                "price" in keys or "rooms" in keys or "addressDetails" in keys
            )

        def walk(node):
            if isinstance(node, dict):
                if looks_like_listing(node):
                    found.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        # de-dupe by id
        seen: set[str] = set()
        unique: list[dict] = []
        for it in found:
            key = str(it.get("id") or it.get("poiId"))
            if key and key not in seen:
                seen.add(key)
                unique.append(it)
        return unique

    def _parse_item(self, item: dict) -> Listing | None:
        poi_id = str(item.get("id") or item.get("poiId") or "")
        if not poi_id:
            return None

        addr = item.get("addressDetails", {}) if isinstance(item.get("addressDetails"), dict) else {}
        city = addr.get("city") or item.get("city", "")
        neighborhood = addr.get("neighbourhood") or addr.get("neighborhood") or ""
        street = addr.get("streetName") or addr.get("street") or ""
        num = addr.get("houseNumber") or ""
        street_full = f"{street} {num}".strip()

        price = _to_int(item.get("price"))
        rooms = _to_float(item.get("rooms") or item.get("beds"))
        size = _to_int(item.get("area") or item.get("size"))
        floor = _to_int(item.get("floor"))

        lat = _to_float(_dig(item, "location", "lat") or item.get("lat"))
        lon = _to_float(_dig(item, "location", "lng") or item.get("lng") or item.get("lon"))

        images = self._extract_images(item)
        description = item.get("description") or item.get("remarks") or ""
        title = " ".join(filter(None, [street_full, neighborhood, city])) or f"Madlan {poi_id}"

        return Listing(
            source=self.name,
            source_id=poi_id,
            url=f"{ITEM_BASE}/{poi_id}",
            title=title,
            description=description,
            price=price,
            rooms=rooms,
            size_sqm=size,
            floor=floor,
            city=city,
            neighborhood=neighborhood,
            street=street_full,
            address=", ".join(filter(None, [street_full, neighborhood, city])),
            lat=lat,
            lon=lon,
            images=images,
        )

    def _extract_images(self, item: dict) -> list[str]:
        urls: list[str] = []
        for key in ("images", "imageList", "photos"):
            val = item.get(key)
            if isinstance(val, list):
                for g in val:
                    if isinstance(g, str):
                        urls.append(g)
                    elif isinstance(g, dict):
                        urls.append(g.get("url") or g.get("src") or "")
        cover = item.get("coverImage") or item.get("mainImage")
        if cover:
            urls.insert(0, cover if isinstance(cover, str) else cover.get("url", ""))
        return list(dict.fromkeys(u for u in urls if u))


def _dig(d: object, *keys: str):
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
