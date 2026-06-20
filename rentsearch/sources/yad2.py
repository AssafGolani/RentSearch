"""Yad2 source adapter — robots.txt compliant.

Yad2's robots.txt (https://www.yad2.co.il/robots.txt) disallows crawling search
pages that carry filter parameters such as ``price``, ``squaremeter``, ``floor``
and the ``imageOnly``/``priceOnly``/``priceDropped`` toggles, and blocks the
``/api/`` path entirely. It *explicitly allows* two things we can build on:

* ``Allow: /realestate/rent?shelter=1`` — the מקלט (shelter) rental page, and
* the published sitemaps under ``/sitemaps/`` (incl. the realestate region index).

So this adapter only ever requests sanctioned URLs:

1. The rental search page ``/realestate/rent`` with **only allowed parameters**
   (``city``, ``rooms`` and, when a shelter is required, ``shelter=1``). The
   disallowed criteria (price, size, floor, ממ"ד) are applied **client-side** by
   the orchestrator's ``SearchFilter.matches``.
2. As a fallback, listing URLs discovered from the realestate **sitemap**.

Listings are read from the page's embedded ``__NEXT_DATA__`` JSON (we never call
the disallowed ``/api/`` endpoints). Every request is additionally checked
against robots.txt by :class:`PoliteClient`, so a future rule change degrades to
"no results from Yad2" rather than a violation.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from .base import Listing, SearchFilter, SourceAdapter
from .http import RobotsDisallowed, make_client

logger = logging.getLogger(__name__)

BASE = "https://www.yad2.co.il"
RENT_SEARCH = f"{BASE}/realestate/rent"
ITEM_BASE = f"{BASE}/realestate/item"
SITEMAP_INDEX = f"{BASE}/sitemaps/realestate/sitemap-index-regions.xml"

# Query parameters that Yad2's robots.txt does NOT disallow for crawling.
# Everything else (price, squaremeter, floor, elevator, parking, ...) must be
# filtered client-side.
ALLOWED_SEARCH_PARAMS = {"city", "rooms", "shelter", "neighborhood", "area", "topArea"}

_ITEM_URL_RE = re.compile(r"/realestate/item/([A-Za-z0-9]+)")


class Yad2Source(SourceAdapter):
    name = "yad2"
    label = "Yad2"

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        with make_client(extra_headers={"Referer": f"{BASE}/realestate/rent"}) as client:
            try:
                listings = self._search_page(client, flt, limit)
            except RobotsDisallowed as exc:
                logger.warning("Yad2 search page blocked by robots.txt: %s", exc)
                listings = []

            if not listings:
                # Compliant fallback: discover via the published sitemap.
                try:
                    listings = self._search_sitemap(client, flt, limit)
                except RobotsDisallowed as exc:
                    logger.warning("Yad2 sitemap blocked by robots.txt: %s", exc)

        logger.info("Yad2: parsed %d listings", len(listings))
        return listings[:limit]

    # ------------------------------------------------------------------ #
    # Primary path: the allowed rental search page.
    # ------------------------------------------------------------------ #

    def _search_page(self, client, flt: SearchFilter, limit: int) -> list[Listing]:
        params = self._build_allowed_params(flt)
        # Build the URL ourselves so the robots check sees the final query string.
        url = RENT_SEARCH
        if flt.require_shelter:
            # Use the explicitly-allowed shelter page as the base.
            url = f"{RENT_SEARCH}?shelter=1"
            params.pop("shelter", None)

        resp = client.get(url, params=params or None)
        resp.raise_for_status()
        return self._listings_from_html(resp.text)

    def _build_allowed_params(self, flt: SearchFilter) -> dict[str, str]:
        params: dict[str, str] = {}
        if flt.city:
            # Yad2 expects a numeric city code; we pass the value through and rely
            # on the orchestrator's client-side city match as a safety net.
            params["city"] = flt.city
        if flt.min_rooms is not None or flt.max_rooms is not None:
            lo = flt.min_rooms if flt.min_rooms is not None else 1
            hi = flt.max_rooms if flt.max_rooms is not None else 20
            params["rooms"] = f"{_fmt(lo)}-{_fmt(hi)}"
        if flt.require_shelter:
            params["shelter"] = "1"
        # Defensive: never emit a disallowed parameter.
        return {k: v for k, v in params.items() if k in ALLOWED_SEARCH_PARAMS}

    # ------------------------------------------------------------------ #
    # Fallback path: sitemap discovery -> individual item pages.
    # ------------------------------------------------------------------ #

    def _search_sitemap(self, client, flt: SearchFilter, limit: int) -> list[Listing]:
        item_urls = self._discover_item_urls(client, limit_urls=limit)
        listings: list[Listing] = []
        for item_url in item_urls:
            try:
                resp = client.get(item_url)
                resp.raise_for_status()
            except (RobotsDisallowed, Exception) as exc:  # noqa: BLE001 - one bad page shouldn't stop the batch
                logger.debug("Yad2: skipping item %s: %s", item_url, exc)
                continue
            page_listings = self._listings_from_html(resp.text)
            listings.extend(page_listings)
            if len(listings) >= limit:
                break
        return listings

    def _discover_item_urls(self, client, limit_urls: int) -> list[str]:
        """Walk the realestate sitemap index and collect listing item URLs."""
        try:
            resp = client.get(SITEMAP_INDEX)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Yad2: sitemap index unavailable: %s", exc)
            return []

        child_sitemaps = _sitemap_locs(resp.text)
        urls: list[str] = []
        for sm in child_sitemaps:
            try:
                sub = client.get(sm)
                sub.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Yad2: sub-sitemap %s failed: %s", sm, exc)
                continue
            for loc in _sitemap_locs(sub.text):
                if _ITEM_URL_RE.search(loc):
                    urls.append(loc)
                    if len(urls) >= limit_urls:
                        return urls
        return urls

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #

    def _listings_from_html(self, html: str) -> list[Listing]:
        data = self._extract_next_data(html)
        if not data:
            return []
        items = self._find_listing_dicts(data)
        listings: list[Listing] = []
        for item in items:
            try:
                listing = self._parse_item(item)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Yad2: skipping unparseable item: %s", exc)
                continue
            if listing is not None:
                listings.append(listing)
        return listings

    def _extract_next_data(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        tag = soup.find("script", id="__NEXT_DATA__")
        if tag and tag.string:
            try:
                return json.loads(tag.string)
            except json.JSONDecodeError:
                pass
        return {}

    def _find_listing_dicts(self, data: dict) -> list[dict]:
        """Deep-walk the hydration blob collecting listing-shaped dicts."""
        found: list[dict] = []

        def looks_like_listing(d: dict) -> bool:
            keys = d.keys()
            has_id = "token" in keys or "orderId" in keys or "adNumber" in keys
            has_meat = "price" in keys or "address" in keys or "additionalDetails" in keys
            return has_id and has_meat

        def walk(node) -> None:
            if isinstance(node, dict):
                if looks_like_listing(node):
                    found.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        # de-dupe by token
        seen: set[str] = set()
        unique: list[dict] = []
        for it in found:
            key = str(it.get("token") or it.get("orderId") or it.get("adNumber"))
            if key and key not in seen:
                seen.add(key)
                unique.append(it)
        return unique

    def _parse_item(self, item: dict) -> Listing | None:
        token = str(item.get("token") or item.get("orderId") or item.get("adNumber") or "")
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
        floor = _to_int(_dig(addr, "house", "floor") or item.get("floor"))

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
        return list(dict.fromkeys(u for u in urls if u))


def _sitemap_locs(xml_text: str) -> list[str]:
    """Extract every <loc> URL from a sitemap or sitemap index."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    locs: list[str] = []
    for el in root.iter():
        if el.tag.endswith("loc") and el.text:
            locs.append(el.text.strip())
    return locs


def _dig(d: object, *keys: str):
    cur = d
    for k in keys:
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return None
    return cur


def _fmt(n) -> str:
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


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
