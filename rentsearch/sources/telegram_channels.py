"""Telegram rental-channel source (MTProto / Telethon).

Many Israeli rental listings are posted to public Telegram channels (which often
cross-post Yad2/Facebook ads). Unlike the websites, Telegram has a stable client
API and no anti-bot wall, so this is the most reliable source.

Reading *public channel history* requires the Telegram **client API** (a user
account), not the Bot API — bots can't read arbitrary channels. We use Telethon.
A one-time login creates a session file (see ``rentsearch.telegram_login``);
after that the adapter runs non-interactively.

Telethon is async; the rest of the scraping pipeline is synchronous. We bridge
the two by running Telethon on its own event loop in a dedicated background
thread and blocking for the result — consistent with how the other (synchronous)
adapters are driven.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path

from .base import (
    MAMAD_KEYWORDS,
    SHELTER_KEYWORDS,
    Listing,
    SearchFilter,
    SourceAdapter,
    _contains_any,
)

logger = logging.getLogger(__name__)

# Where downloaded post photos are cached so the bot can re-send them.
IMAGE_CACHE_DIR = Path("data/telegram_images")

# --------------------------------------------------------------------------- #
# Pure text parsing (no network / Telethon — unit-tested directly)
# --------------------------------------------------------------------------- #

# Price: a 4-6 digit number (optionally comma-grouped) next to a currency token.
_PRICE_RE = re.compile(
    r'(\d{1,3}(?:,\d{3})+|\d{4,6})\s*(?:₪|ש"?ח|שקל|nis)', re.IGNORECASE
)
# Or an explicit "מחיר: 6500" style.
_PRICE_LABEL_RE = re.compile(r'(?:מחיר|price)\D{0,6}(\d{1,3}(?:,\d{3})+|\d{3,6})', re.IGNORECASE)
_ROOMS_RE = re.compile(r'(\d(?:\.\d)?)\s*(?:חד(?:רים|\'|׳)?|חדר)')
_SIZE_RE = re.compile(r'(\d{2,3})\s*(?:מ"?ר|מ׳ר|מטר(?:\s*רבוע)?|sqm|m2|מ״ר)', re.IGNORECASE)

# Plausible monthly-rent bounds (₪) — filters out phone numbers, sizes, years.
_MIN_RENT, _MAX_RENT = 1000, 100000


def _to_int(num: str) -> int | None:
    try:
        return int(num.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_price(text: str) -> int | None:
    candidates: list[int] = []
    for match in _PRICE_RE.finditer(text):
        val = _to_int(match.group(1))
        if val is not None:
            candidates.append(val)
    for match in _PRICE_LABEL_RE.finditer(text):
        val = _to_int(match.group(1))
        if val is not None:
            candidates.append(val)
    plausible = [c for c in candidates if _MIN_RENT <= c <= _MAX_RENT]
    if not plausible:
        return None
    # The smallest plausible figure is usually the rent (larger ones are often
    # square-meterage-times-something or deposits); prefer the most common.
    return min(plausible)


def parse_rooms(text: str) -> float | None:
    match = _ROOMS_RE.search(text)
    if not match:
        return None
    try:
        rooms = float(match.group(1))
    except ValueError:
        return None
    return rooms if 1 <= rooms <= 15 else None


def parse_size(text: str) -> int | None:
    match = _SIZE_RE.search(text)
    if not match:
        return None
    size = _to_int(match.group(1))
    return size if size and 10 <= size <= 1000 else None


def parse_message_fields(text: str) -> dict:
    """Extract structured rental fields from a free-text Telegram post."""
    text = text or ""
    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return {
        "title": first_line[:120] or "Telegram listing",
        "price": parse_price(text),
        "rooms": parse_rooms(text),
        "size_sqm": parse_size(text),
        "has_mamad": _contains_any(text, MAMAD_KEYWORDS),
        "has_shelter": _contains_any(text, SHELTER_KEYWORDS),
    }


def looks_like_listing(text: str) -> bool:
    """Heuristic: a post is a rental listing if it mentions rent + a price/rooms."""
    if not text:
        return False
    rent_words = ("להשכרה", "השכרה", "מושכר", "for rent", "דירה")
    has_rent_word = any(w in text for w in rent_words)
    return has_rent_word and (parse_price(text) is not None or parse_rooms(text) is not None)


# --------------------------------------------------------------------------- #
# Async bridge: run Telethon coroutines on a dedicated background loop
# --------------------------------------------------------------------------- #


class _AsyncBridge:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run, name="telethon-loop", daemon=True
                )
                self._thread.start()
            return self._loop

    def _run(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro):
        loop = self._ensure()
        return asyncio.run_coroutine_threadsafe(coro, loop).result()


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #


class TelegramChannelSource(SourceAdapter):
    name = "telegram"
    label = "Telegram"
    enabled_by_default = False  # needs API credentials + a one-time login

    def __init__(self) -> None:
        from ..config import settings

        self._settings = settings
        self._bridge = _AsyncBridge()
        self._client = None
        self._warned = False

    @property
    def is_configured(self) -> bool:
        s = self._settings
        session_exists = Path(f"{s.telegram_session_path}.session").exists()
        return bool(s.telegram_api_id and s.telegram_api_hash and s.telegram_channels and session_exists)

    def search(self, flt: SearchFilter, limit: int = 40) -> list[Listing]:
        if not self.is_configured:
            if not self._warned:
                logger.warning(
                    "Telegram source disabled: set TELEGRAM_API_ID, TELEGRAM_API_HASH, "
                    "TELEGRAM_CHANNELS and run `python -m rentsearch.telegram_login` first."
                )
                self._warned = True
            return []
        return self._bridge.run(self._search_async(flt, limit))

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        from telethon import TelegramClient

        s = self._settings
        client = TelegramClient(s.telegram_session_path, s.telegram_api_id, s.telegram_api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise RuntimeError(
                "Telegram session is not authorized. Run `python -m rentsearch.telegram_login`."
            )
        self._client = client
        return client

    async def _search_async(self, flt: SearchFilter, limit: int) -> list[Listing]:
        client = await self._ensure_client()
        channels = self._settings.telegram_channels
        per_channel = max(10, limit // max(1, len(channels)))
        IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        listings: list[Listing] = []
        for channel in channels:
            try:
                async for message in client.iter_messages(channel, limit=per_channel):
                    listing = await self._message_to_listing(client, channel, message)
                    if listing is not None:
                        listings.append(listing)
            except Exception as exc:  # noqa: BLE001 - one bad channel shouldn't stop the rest
                logger.warning("Telegram: failed reading channel %s: %s", channel, exc)
        logger.info("Telegram: parsed %d listings from %d channels", len(listings), len(channels))
        return listings[:limit]

    async def _message_to_listing(self, client, channel: str, message) -> Listing | None:
        text = message.message or getattr(message, "text", "") or ""
        if not looks_like_listing(text):
            return None

        fields = parse_message_fields(text)
        images = await self._download_photo(client, channel, message)

        return Listing(
            source=self.name,
            source_id=f"{channel}:{message.id}",
            url=f"https://t.me/{channel}/{message.id}",
            title=fields["title"],
            description=text,
            price=fields["price"],
            rooms=fields["rooms"],
            size_sqm=fields["size_sqm"],
            images=images,
            has_mamad=fields["has_mamad"],
            has_shelter=fields["has_shelter"],
        )

    async def _download_photo(self, client, channel: str, message) -> list[str]:
        if not getattr(message, "photo", None):
            return []
        dest = IMAGE_CACHE_DIR / f"{channel}_{message.id}.jpg"
        if dest.exists():
            return [str(dest)]
        try:
            saved = await client.download_media(message, file=str(dest))
            return [str(saved)] if saved else []
        except Exception as exc:  # noqa: BLE001
            logger.debug("Telegram: photo download failed for %s/%s: %s", channel, message.id, exc)
            return []
