"""Yad2 source adapter.

Yad2 (yad2.co.il) is the largest second-hand marketplace in Israel and the
primary source for rental listings. Its web app is backed by a JSON gateway
(``gw.yad2.co.il``) that returns structured feed items. We query that gateway
and normalize each feed item into a :class:`Listing`.

Site internals change over time; :meth:`_parse_item` is intentionally tolerant
of missing/renamed fields so a partial schema change degrades gracefully rather
than crashing the whole search run.
"""
from __future__ import annotations

import logging

from .base import Listing, SearchFilter, SourceAdapter
from .http import make_client

logger = logging.getLogger(__name__)

# Public feed gateway used by the Yad2 SPA for the rentals category.
FEED_URL = "https://gw.yad2.co.il/realestate-feed/rent/map"
ITEM_BASE = "https://www.yad2.co.il/realestate/item"


class Yad2Source(SourceAdapter):
    name = "yad2"
    label = "Yad2"

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        params = self._build_params(flt, limit)
        with make_client(extra_headers={"mainsite_version_commit": "stable"}) as client:
            resp = client.get(FEED_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()

        items = self._extract_items(payload)
        listings: list[Listing] = []
        for item in items:
            try:
                listing = self._parse_item(item)
            except Exception as exc:  # one bad item shouldn't kill the batch
                logger.debug("Yad2: skipping unparseable item: %s", exc)
                continue
            if listing is not None:
                listings.append(listing)
        logger.info("Yad2: parsed %d listings", len(listings))
        return listings[:limit]

    # ------------------------------------------------------------------ #

    def _build_params(self, flt: SearchFilter, limit: int) -> dict:
        params: dict[str, object] = {"forceLdLoad": "true", "limit": limit}
        if flt.min_price is not None or flt.max_price is not None:
            lo = flt.min_price or 0
            hi = flt.max_price or 100000
            params["price"] = f"{lo}-{hi}"
        if flt.min_rooms is not None or flt.max_rooms is not None:
            lo = flt.min_rooms or 1
            hi = flt.max_rooms or 20
            params["rooms"] = f"{lo}-{hi}"
        if flt.min_size is not None or flt.max_size is not None:
            lo = flt.min_size or 0
            hi = flt.max_size or 1000
            params["squaremeter"] = f"{lo}-{hi}"
        if flt.city:
            params["city"] = flt.city
        return params

    def _extract_items(self, payload: dict) -> list[dict]:
        """Find the list of feed items regardless of minor envelope changes."""
        if not isinstance(payload, dict):
            return []
        data = payload.get("data", payload)
        for key in ("markers", "feed_items", "items", "results"):
            if isinstance(data, dict) and isinstance(data.get(key), list):
                return data[key]
        if isinstance(data, list):
            return data
        return []

    def _parse_item(self, item: dict) -> Listing | None:
        if not isinstance(item, dict):
            return None

        token = str(item.get("token") or item.get("id") or item.get("orderId") or "")
        if not token:
            return None

        addr = item.get("address", {}) if isinstance(item.get("address"), dict) else {}
        city = _dig(addr, "city", "text") or item.get("city", "")
        neighborhood = _dig(addr, "neighborhood", "text") or item.get("neighborhood", "")
        street = _dig(addr, "street", "text") or item.get("street", "")
        house_num = _dig(addr, "house", "number")
        street_full = f"{street} {house_num}".strip() if house_num else street

        coords = _dig(addr, "coords") or item.get("coordinates", {})
        lat = _to_float(coords.get("lat")) if isinstance(coords, dict) else None
        lon = _to_float(coords.get("lon") or coords.get("lng")) if isinstance(coords, dict) else None

        price = _to_int(item.get("price") or _dig(item, "price", "value"))

        info = item.get("additionalDetails", {}) if isinstance(item.get("additionalDetails"), dict) else {}
        rooms = _to_float(_dig(info, "roomsCount") or item.get("rooms"))
        size = _to_int(_dig(info, "squareMeter") or item.get("square_meters"))
        floor = _to_int(_dig(item, "address", "house", "floor") or item.get("floor"))

        images = self._extract_images(item)
        title = " ".join(filter(None, [street_full, neighborhood, city])) or f"Yad2 {token}"
        description = item.get("text") or _dig(item, "metaData", "description") or ""

        return Listing(
            source=self.name,
            source_id=token,
            url=f"{ITEM_BASE}/{token}",
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
        meta = item.get("metaData", {}) if isinstance(item.get("metaData"), dict) else {}
        cover = meta.get("coverImage") or item.get("coverImage")
        if cover:
            urls.append(cover)
        gallery = meta.get("images") or item.get("images") or []
        if isinstance(gallery, list):
            for g in gallery:
                if isinstance(g, str):
                    urls.append(g)
                elif isinstance(g, dict) and g.get("src"):
                    urls.append(g["src"])
        # de-dupe, keep order
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
