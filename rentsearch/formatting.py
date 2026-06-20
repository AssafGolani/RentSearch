"""Render listings into Telegram messages (HTML) and inline keyboards."""
from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .sources.base import Listing

SOURCE_LABELS = {
    "yad2": "Yad2",
    "madlan": "Madlan",
    "facebook": "Facebook",
}


def _fmt_price(listing: Listing) -> str:
    if not listing.has_price:
        return "—"
    symbol = {"ILS": "₪", "USD": "$", "EUR": "€"}.get(listing.currency, "₪")
    return f"{listing.price:,} {symbol}"


def _fmt_num(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_caption(listing: Listing, filter_name: str | None = None) -> str:
    """Build an HTML caption for a listing message."""
    label = SOURCE_LABELS.get(listing.source, listing.source.title())
    lines: list[str] = []

    title = escape(listing.title or "Property")
    lines.append(f"🏠 <b>{title}</b>")

    facts = [
        f"💰 {escape(_fmt_price(listing))}",
        f"🚪 {_fmt_num(listing.rooms)} rooms",
        f"📐 {_fmt_num(listing.size_sqm)} m²",
    ]
    if listing.floor is not None:
        facts.append(f"🏢 floor {listing.floor}")
    lines.append(" · ".join(facts))

    if listing.full_address:
        lines.append(f"📍 {escape(listing.full_address)}")

    badges = []
    if listing.has_mamad:
        badges.append('🛡 ממ"ד')
    if listing.has_shelter:
        badges.append("🚨 מקלט")
    if badges:
        lines.append(" · ".join(badges))

    if listing.description:
        desc = listing.description.strip().replace("\n", " ")
        if len(desc) > 220:
            desc = desc[:217] + "…"
        lines.append(f"\n{escape(desc)}")

    footer = f"\n📡 <i>{escape(label)}</i>"
    if filter_name:
        footer += f" · 🔔 <i>{escape(filter_name)}</i>"
    lines.append(footer)

    return "\n".join(lines)


def render_keyboard(listing: Listing, is_favorite: bool = False) -> InlineKeyboardMarkup:
    """Inline buttons: open listing, map pin, favorite toggle."""
    fav_label = "★ Saved" if is_favorite else "☆ Save"
    rows = [
        [
            InlineKeyboardButton("🔗 Open listing", url=listing.url),
            InlineKeyboardButton("🗺 Map", url=listing.google_maps_url()),
        ],
        [
            InlineKeyboardButton(fav_label, callback_data=f"fav:{listing.global_id}"),
        ],
    ]
    return InlineKeyboardMarkup(rows)
