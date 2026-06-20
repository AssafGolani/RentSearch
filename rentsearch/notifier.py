"""Send listing notifications to Telegram chats and the broadcast channel.

A listing is sent as a photo (first image) with an HTML caption and inline
buttons. We keep a short in-memory cache mapping ``global_id`` -> a serialized
Listing so the favorite button's callback can reconstruct it without re-scraping.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from .config import settings
from .formatting import render_caption, render_keyboard
from .sources.base import Listing

logger = logging.getLogger(__name__)


def _photo_arg(image: str):
    """Return a value send_photo accepts: a Path for local files, else the URL.

    Telegram-channel listings store a downloaded local file path in ``images``;
    website listings store a remote URL. PTB reads a ``Path`` as an upload but
    treats a bare string as a URL/file_id, so we must distinguish them.
    """
    if image and os.path.exists(image):
        return Path(image)
    return image

# global_id -> JSON snapshot, used by the favorite callback handler.
_LISTING_CACHE: dict[str, str] = {}
_CACHE_LIMIT = 2000


def cache_listing(listing: Listing) -> None:
    if len(_LISTING_CACHE) > _CACHE_LIMIT:
        # drop oldest ~10%
        for key in list(_LISTING_CACHE)[: _CACHE_LIMIT // 10]:
            _LISTING_CACHE.pop(key, None)
    _LISTING_CACHE[listing.global_id] = _serialize(listing)


def get_cached_listing(global_id: str) -> dict | None:
    raw = _LISTING_CACHE.get(global_id)
    return json.loads(raw) if raw else None


async def send_listing(bot: Bot, chat_id: int | str, listing: Listing, filter_name: str | None = None) -> None:
    """Send a single listing to a chat. Falls back to text if the image fails."""
    cache_listing(listing)
    caption = render_caption(listing, filter_name)
    keyboard = render_keyboard(listing)

    if listing.images:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=_photo_arg(listing.images[0]),
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            return
        except TelegramError as exc:
            logger.debug("send_photo failed (%s); falling back to text", exc)

    # Per the spec we only surface listings *with* an image, but if Telegram
    # rejects the remote image URL we still deliver the info as text.
    await bot.send_message(
        chat_id=chat_id,
        text=caption,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_web_page_preview=False,
    )


async def broadcast_listing(bot: Bot, listing: Listing, filter_name: str | None = None) -> None:
    """Send to the configured broadcast channel, if any."""
    if settings.telegram_channel_id:
        try:
            await send_listing(bot, settings.telegram_channel_id, listing, filter_name)
        except TelegramError as exc:
            logger.warning("Channel broadcast failed: %s", exc)


def _serialize(listing: Listing) -> str:
    return json.dumps(
        {
            "source": listing.source,
            "source_id": listing.source_id,
            "url": listing.url,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "currency": listing.currency,
            "rooms": listing.rooms,
            "size_sqm": listing.size_sqm,
            "floor": listing.floor,
            "city": listing.city,
            "neighborhood": listing.neighborhood,
            "street": listing.street,
            "address": listing.address,
            "lat": listing.lat,
            "lon": listing.lon,
            "images": listing.images,
            "has_mamad": listing.has_mamad,
            "has_shelter": listing.has_shelter,
        },
        ensure_ascii=False,
    )


def listing_from_dict(data: dict) -> Listing:
    return Listing(
        source=data["source"],
        source_id=data["source_id"],
        url=data["url"],
        title=data.get("title", ""),
        description=data.get("description", ""),
        price=data.get("price"),
        currency=data.get("currency", "ILS"),
        rooms=data.get("rooms"),
        size_sqm=data.get("size_sqm"),
        floor=data.get("floor"),
        city=data.get("city", ""),
        neighborhood=data.get("neighborhood", ""),
        street=data.get("street", ""),
        address=data.get("address", ""),
        lat=data.get("lat"),
        lon=data.get("lon"),
        images=data.get("images", []),
        has_mamad=data.get("has_mamad", False),
        has_shelter=data.get("has_shelter", False),
    )
