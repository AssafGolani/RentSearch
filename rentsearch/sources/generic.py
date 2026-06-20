"""Generic adapter for arbitrary Israeli real-estate websites.

Many Israeli real-estate sites (HomeLess, WinWin, Komo, agency sites, ...)
publish listings with schema.org structured data embedded as JSON-LD
(``<script type="application/ld+json">``). This adapter lets you plug in any
such site by URL without writing a bespoke parser: it reads JSON-LD
``RealEstateListing`` / ``Apartment`` / ``Product`` / ``Residence`` objects and
normalizes them.

Configure sites in ``config.yaml`` under ``generic_sources`` (see README).
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Listing, SearchFilter, SourceAdapter
from .http import make_client

logger = logging.getLogger(__name__)

REAL_ESTATE_TYPES = {
    "realestatelisting",
    "apartment",
    "residence",
    "house",
    "singlefamilyresidence",
    "product",
    "offer",
}


class GenericSource(SourceAdapter):
    """One instance per configured external site."""

    enabled_by_default = False

    def __init__(self, name: str, label: str, search_url_template: str):
        # e.g. search_url_template = "https://www.example.co.il/rent?city={city}"
        self.name = name
        self.label = label
        self.search_url_template = search_url_template

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        url = self.search_url_template.format(
            city=flt.city or "",
            min_price=flt.min_price or "",
            max_price=flt.max_price or "",
        )
        with make_client() as client:
            resp = client.get(url)
            resp.raise_for_status()
            html = resp.text

        listings = self._parse_jsonld(html, base_url=url)
        logger.info("%s: parsed %d listings", self.label, len(listings))
        return listings[:limit]

    # ------------------------------------------------------------------ #

    def _parse_jsonld(self, html: str, base_url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        listings: list[Listing] = []
        for tag in soup.find_all("script", type="application/ld+json"):
            if not tag.string:
                continue
            try:
                data = json.loads(tag.string)
            except json.JSONDecodeError:
                continue
            for obj in self._iter_objects(data):
                listing = self._obj_to_listing(obj, base_url)
                if listing:
                    listings.append(listing)
        # de-dupe by source_id
        seen: set[str] = set()
        unique: list[Listing] = []
        for l in listings:
            if l.source_id not in seen:
                seen.add(l.source_id)
                unique.append(l)
        return unique

    def _iter_objects(self, data):
        """Yield candidate real-estate objects from a JSON-LD document."""
        if isinstance(data, list):
            for d in data:
                yield from self._iter_objects(d)
        elif isinstance(data, dict):
            if "@graph" in data:
                yield from self._iter_objects(data["@graph"])
                return
            types = data.get("@type", "")
            if isinstance(types, list):
                type_set = {str(t).lower() for t in types}
            else:
                type_set = {str(types).lower()}
            if type_set & REAL_ESTATE_TYPES:
                yield data
            if "itemListElement" in data:
                yield from self._iter_objects(data["itemListElement"])
            if "item" in data and isinstance(data["item"], dict):
                yield from self._iter_objects(data["item"])

    def _obj_to_listing(self, obj: dict, base_url: str) -> Listing | None:
        url = obj.get("url") or obj.get("@id") or ""
        if url:
            url = urljoin(base_url, url)
        source_id = obj.get("sku") or obj.get("productID") or url or obj.get("name", "")
        if not source_id:
            return None

        offers = obj.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _to_int(obj.get("price") or (offers.get("price") if isinstance(offers, dict) else None))

        addr = obj.get("address", {})
        if isinstance(addr, str):
            city, street = "", addr
        elif isinstance(addr, dict):
            city = addr.get("addressLocality", "")
            street = addr.get("streetAddress", "")
        else:
            city, street = "", ""

        geo = obj.get("geo", {})
        lat = _to_float(geo.get("latitude")) if isinstance(geo, dict) else None
        lon = _to_float(geo.get("longitude")) if isinstance(geo, dict) else None

        images = self._extract_images(obj)
        rooms = _to_float(obj.get("numberOfRooms"))
        size = self._extract_size(obj)

        return Listing(
            source=self.name,
            source_id=str(source_id),
            url=url or base_url,
            title=obj.get("name", "") or f"{self.label}",
            description=_clean(obj.get("description", "")),
            price=price,
            rooms=rooms,
            size_sqm=size,
            city=city,
            street=street,
            address=", ".join(filter(None, [street, city])),
            lat=lat,
            lon=lon,
            images=images,
        )

    def _extract_images(self, obj: dict) -> list[str]:
        img = obj.get("image")
        urls: list[str] = []
        if isinstance(img, str):
            urls.append(img)
        elif isinstance(img, list):
            for i in img:
                if isinstance(i, str):
                    urls.append(i)
                elif isinstance(i, dict) and i.get("url"):
                    urls.append(i["url"])
        elif isinstance(img, dict) and img.get("url"):
            urls.append(img["url"])
        return list(dict.fromkeys(urls))

    def _extract_size(self, obj: dict) -> int | None:
        size = obj.get("floorSize")
        if isinstance(size, dict):
            return _to_int(size.get("value"))
        return _to_int(size)


def _clean(text) -> str:
    if not isinstance(text, str):
        return ""
    return BeautifulSoup(text, "lxml").get_text(" ", strip=True)


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
