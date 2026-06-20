"""Command and callback handlers for the RentSearch bot."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..db import session_scope
from ..models import Favorite, SavedFilter
from ..notifier import (
    broadcast_listing,
    get_cached_listing,
    listing_from_dict,
    send_listing,
)
from ..search import collect_new_listings
from ..sources import all_sources

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🏠 <b>RentSearch</b> — Israeli rental finder\n\n"
    "I search <b>Yad2</b>, <b>Madlan</b>, <b>Facebook</b> and other Israeli "
    "real-estate sites on a schedule and alert you about new matching properties "
    "— always with a photo, a price, and a map pin. Duplicates across sources "
    "are filtered out automatically.\n\n"
    "<b>Commands</b>\n"
    "/newfilter — create a search filter (city, price, rooms, ממ\"ד, מקלט…)\n"
    "/filters — list & manage your saved filters\n"
    "/run — search all your filters right now\n"
    "/favorites — show properties you've saved\n"
    "/sources — list the property sources I search\n"
    "/help — show this message\n\n"
    "Tip: every result has ☆ <b>Save</b>, 🗺 <b>Map</b> and 🔗 <b>Open</b> buttons."
)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["📡 <b>Sources I search</b>:"]
    for s in all_sources():
        status = "" if getattr(s, "is_configured", True) else " <i>(needs setup)</i>"
        lines.append(f"• <b>{s.label}</b> (<code>{s.name}</code>){status}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_filters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with session_scope() as session:
        filters_ = (
            session.query(SavedFilter)
            .filter(SavedFilter.chat_id == chat_id)
            .order_by(SavedFilter.created_at)
            .all()
        )
        if not filters_:
            await update.message.reply_text(
                "You have no saved filters yet. Create one with /newfilter."
            )
            return
        for f in filters_:
            summary = f.summary()
            toggle = "⏸ Pause" if f.active else "▶️ Resume"
            keyboard = InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton("🔍 Run", callback_data=f"runf:{f.id}"),
                    InlineKeyboardButton(toggle, callback_data=f"togglef:{f.id}"),
                    InlineKeyboardButton("🗑 Delete", callback_data=f"delf:{f.id}"),
                ]]
            )
            await update.message.reply_text(
                summary, parse_mode=ParseMode.HTML, reply_markup=keyboard
            )


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text("🔍 Searching all your active filters…")
    total = await _run_filters_for_chat(context, chat_id)
    if total == 0:
        await update.message.reply_text(
            "No new properties right now. I'll keep checking automatically and "
            "notify you when something new appears."
        )
    else:
        await update.message.reply_text(f"✅ Sent {total} new propert{'y' if total == 1 else 'ies'}.")


async def cmd_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    with session_scope() as session:
        favs = (
            session.query(Favorite)
            .filter(Favorite.chat_id == chat_id)
            .order_by(Favorite.created_at.desc())
            .all()
        )
        if not favs:
            await update.message.reply_text(
                "You haven't saved any favorites yet. Tap ☆ Save on any property."
            )
            return
        payloads = [f.deserialize() for f in favs]

    await update.message.reply_text(f"⭐ You have {len(payloads)} saved propert"
                                    f"{'y' if len(payloads) == 1 else 'ies'}:")
    for data in payloads:
        listing = listing_from_dict(data)
        await send_listing(context.bot, chat_id, listing, filter_name="favorite")


# --------------------------------------------------------------------------- #
# Callback query handlers (inline buttons)
# --------------------------------------------------------------------------- #

async def on_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    global_id = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id

    data = get_cached_listing(global_id)
    with session_scope() as session:
        existing = (
            session.query(Favorite)
            .filter(Favorite.chat_id == chat_id, Favorite.global_id == global_id)
            .first()
        )
        if existing:
            session.delete(existing)
            await query.answer("Removed from favorites")
        else:
            if not data:
                await query.answer("Sorry, this listing expired. Re-run the search.", show_alert=True)
                return
            listing = listing_from_dict(data)
            session.add(
                Favorite(
                    chat_id=chat_id,
                    global_id=global_id,
                    payload=Favorite.serialize_listing(listing),
                )
            )
            await query.answer("⭐ Saved to favorites")


async def on_run_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Searching…")
    filter_id = int(query.data.split(":", 1)[1])
    chat_id = query.message.chat_id
    total = await _run_one_filter(context, chat_id, filter_id)
    if total == 0:
        await query.message.reply_text("No new properties for this filter right now.")
    else:
        await query.message.reply_text(f"✅ Sent {total} new propert{'y' if total == 1 else 'ies'}.")


async def on_toggle_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    filter_id = int(query.data.split(":", 1)[1])
    with session_scope() as session:
        f = session.get(SavedFilter, filter_id)
        if not f or f.chat_id != query.message.chat_id:
            await query.answer("Filter not found", show_alert=True)
            return
        f.active = not f.active
        state = "resumed ▶️" if f.active else "paused ⏸"
        summary = f.summary()
    await query.answer(f"Filter {state}")
    await query.edit_message_text(summary, parse_mode=ParseMode.HTML, reply_markup=query.message.reply_markup)


async def on_delete_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    filter_id = int(query.data.split(":", 1)[1])
    with session_scope() as session:
        f = session.get(SavedFilter, filter_id)
        if not f or f.chat_id != query.message.chat_id:
            await query.answer("Filter not found", show_alert=True)
            return
        name = f.name
        session.delete(f)
    await query.answer(f"Deleted '{name}'")
    await query.edit_message_text(f"🗑 Deleted filter <b>{name}</b>.", parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

async def _run_filters_for_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> int:
    total = 0
    with session_scope() as session:
        filters_ = (
            session.query(SavedFilter)
            .filter(SavedFilter.chat_id == chat_id, SavedFilter.active.is_(True))
            .all()
        )
        jobs = [(f.id, f.name) for f in filters_]
    for filter_id, _name in jobs:
        total += await _run_one_filter(context, chat_id, filter_id)
    return total


async def _run_one_filter(context: ContextTypes.DEFAULT_TYPE, chat_id: int, filter_id: int) -> int:
    with session_scope() as session:
        saved = session.get(SavedFilter, filter_id)
        if not saved or saved.chat_id != chat_id:
            return 0
        name = saved.name
        try:
            new_listings = collect_new_listings(saved, session)
        except Exception as exc:
            logger.exception("Manual run of filter %s failed: %s", filter_id, exc)
            return 0
        session.commit()
        # Detach plain data we need before the session closes.
        listings = list(new_listings)

    sent = 0
    for listing in listings:
        try:
            await send_listing(context.bot, chat_id, listing, name)
            await broadcast_listing(context.bot, listing, name)
            sent += 1
        except Exception as exc:
            logger.warning("Failed to send listing: %s", exc)
    return sent
