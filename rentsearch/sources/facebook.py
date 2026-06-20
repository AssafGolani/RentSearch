"""Facebook source adapter (Marketplace & rental groups).

Facebook does not offer a public rentals API, requires an authenticated
session, and rate-limits/obfuscates heavily. This adapter therefore works in an
*opt-in, bring-your-own-session* mode:

* Provide a valid ``c_user`` + ``xs`` cookie pair via the ``FACEBOOK_COOKIE``
  env var (copied from a logged-in browser session), and
* Provide one or more Marketplace/group search URLs in ``FACEBOOK_SEARCH_URLS``
  (comma-separated).

Without those it stays disabled and returns no listings (logged once), so the
rest of the system keeps working. When configured, it extracts the embedded
GraphQL/JSON payload from the returned HTML and normalizes what it can.

Respect Facebook's Terms of Service and only use an account you control.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .base import Listing, SearchFilter, SourceAdapter
from .http import make_client

logger = logging.getLogger(__name__)


class FacebookSource(SourceAdapter):
    name = "facebook"
    label = "Facebook"
    enabled_by_default = False  # needs a user-supplied session to function

    def __init__(self) -> None:
        self.cookie = os.getenv("FACEBOOK_COOKIE", "").strip()
        raw_urls = os.getenv("FACEBOOK_SEARCH_URLS", "").strip()
        self.search_urls = [u.strip() for u in raw_urls.split(",") if u.strip()]
        self._warned = False

    @property
    def is_configured(self) -> bool:
        return bool(self.cookie and self.search_urls)

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        if not self.is_configured:
            if not self._warned:
                logger.warning(
                    "Facebook source disabled: set FACEBOOK_COOKIE and "
                    "FACEBOOK_SEARCH_URLS to enable it."
                )
                self._warned = True
            return []

        headers = {"Cookie": self.cookie}
        listings: list[Listing] = []
        with make_client(extra_headers=headers) as client:
            for url in self.search_urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    listings.extend(self._parse_html(resp.text, url))
                except Exception as exc:
                    logger.warning("Facebook: failed to fetch %s: %s", url, exc)
                if len(listings) >= limit:
                    break
        logger.info("Facebook: parsed %d listings", len(listings))
        return listings[:limit]

    # ------------------------------------------------------------------ #

    def _parse_html(self, html: str, source_url: str) -> list[Listing]:
        """Best-effort extraction of marketplace items from embedded JSON."""
        listings: list[Listing] = []
        # Facebook embeds many <script type="application/json"> blobs. Marketplace
        # items contain a "marketplace_listing_title" / "listing_price" shape.
        for blob in re.findall(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', html, re.S):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            self._collect(data, source_url, listings)
        # de-dupe by source_id
        seen: set[str] = set()
        unique: list[Listing] = []
        for l in listings:
            if l.source_id not in seen:
                seen.add(l.source_id)
                unique.append(l)
        return unique

    def _collect(self, node, source_url: str, out: list[Listing]) -> None:
        if isinstance(node, dict):
            if "marketplace_listing_title" in node or (
                node.get("__typename") == "MarketplaceListing"
            ):
                listing = self._node_to_listing(node, source_url)
                if listing:
                    out.append(listing)
            for v in node.values():
                self._collect(v, source_url, out)
        elif isinstance(node, list):
            for v in node:
                self._collect(v, source_url, out)

    def _node_to_listing(self, node: dict, source_url: str) -> Listing | None:
        item_id = str(node.get("id") or node.get("story_key") or "")
        if not item_id:
            return None
        title = node.get("marketplace_listing_title") or node.get("custom_title") or ""
        price_node = node.get("listing_price") or node.get("formatted_price") or {}
        price = None
        if isinstance(price_node, dict):
            price = _to_int(price_node.get("amount"))
        loc = node.get("location") or {}
        city = ""
        if isinstance(loc, dict):
            city = _dig(loc, "reverse_geocode", "city") or ""
        lat = _to_float(_dig(loc, "latitude"))
        lon = _to_float(_dig(loc, "longitude"))

        images: list[str] = []
        primary = node.get("primary_listing_photo") or {}
        img_uri = _dig(primary, "image", "uri")
        if img_uri:
            images.append(img_uri)

        return Listing(
            source=self.name,
            source_id=item_id,
            url=f"https://www.facebook.com/marketplace/item/{item_id}",
            title=title or f"Facebook {item_id}",
            description=node.get("redacted_description", {}).get("text", "") if isinstance(
                node.get("redacted_description"), dict
            ) else "",
            price=price,
            city=city,
            lat=lat,
            lon=lon,
            images=images,
        )


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
        return int(float(str(value).replace(",", "").replace("₪", "").strip()))
    except (ValueError, TypeError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None
