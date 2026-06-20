"""Step-by-step /newfilter conversation for creating a saved filter."""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ..db import session_scope
from ..models import SavedFilter
from ..sources import all_sources

logger = logging.getLogger(__name__)

# Conversation states
(NAME, CITY, PRICE, ROOMS, MAMAD, SHELTER, SOURCES) = range(7)

SKIP_HINT = "Send a value, or /skip to leave it empty."


def _parse_range(text: str) -> tuple[float | None, float | None]:
    """Parse 'min-max', 'min-', '-max', or a single number into (min, max)."""
    text = text.strip().replace(" ", "")
    if not text:
        return None, None
    if "-" in text:
        lo, _, hi = text.partition("-")
        return _num(lo), _num(hi)
    n = _num(text)
    return n, None


def _num(s: str) -> float | None:
    s = s.strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(n) -> int | None:
    return int(n) if n is not None else None


async def start_new_filter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_filter"] = {}
    await update.message.reply_text(
        "🆕 Let's create a search filter.\n\nFirst, give it a <b>name</b> "
        "(e.g. \"3 rooms Tel Aviv with mamad\"):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return NAME


async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_filter"]["name"] = update.message.text.strip()[:120]
    await update.message.reply_text(
        "📍 Which <b>city</b>? (e.g. תל אביב, ירושלים, חיפה)\n" + SKIP_HINT,
        parse_mode="HTML",
    )
    return CITY


async def set_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_filter"]["city"] = update.message.text.strip()
    await update.message.reply_text(
        "💰 <b>Price range</b> in ₪/month? (e.g. <code>4000-7000</code>, "
        "<code>5000-</code> for min only)\n" + SKIP_HINT,
        parse_mode="HTML",
    )
    return PRICE


async def skip_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "💰 <b>Price range</b> in ₪/month? (e.g. <code>4000-7000</code>)\n" + SKIP_HINT,
        parse_mode="HTML",
    )
    return PRICE


async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lo, hi = _parse_range(update.message.text)
    context.user_data["new_filter"]["min_price"] = _int(lo)
    context.user_data["new_filter"]["max_price"] = _int(hi)
    return await _ask_rooms(update)


async def skip_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _ask_rooms(update)


async def _ask_rooms(update: Update) -> int:
    await update.message.reply_text(
        "🚪 <b>Rooms range</b>? (e.g. <code>3-4</code>, <code>3-</code>)\n" + SKIP_HINT,
        parse_mode="HTML",
    )
    return ROOMS


async def set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lo, hi = _parse_range(update.message.text)
    context.user_data["new_filter"]["min_rooms"] = lo
    context.user_data["new_filter"]["max_rooms"] = hi
    return await _ask_mamad(update)


async def skip_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _ask_mamad(update)


def _yes_no_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Yes", callback_data="yes"),
          InlineKeyboardButton("❌ No", callback_data="no")]]
    )


async def _ask_mamad(update: Update) -> int:
    await update.message.reply_text(
        '🛡 Require a <b>ממ"ד</b> (protected room)?',
        parse_mode="HTML",
        reply_markup=_yes_no_keyboard(),
    )
    return MAMAD


async def set_mamad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["new_filter"]["require_mamad"] = query.data == "yes"
    await query.edit_message_text(
        f'🛡 ממ"ד required: {"✅" if query.data == "yes" else "❌"}'
    )
    await query.message.reply_text(
        "🚨 Require a <b>מקלט</b> (bomb shelter)?",
        parse_mode="HTML",
        reply_markup=_yes_no_keyboard(),
    )
    return SHELTER


async def set_shelter(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["new_filter"]["require_shelter"] = query.data == "yes"
    await query.edit_message_text(
        f'🚨 מקלט required: {"✅" if query.data == "yes" else "❌"}'
    )

    # Build a multi-select-ish sources prompt (default: all).
    names = ", ".join(s.name for s in all_sources())
    await query.message.reply_text(
        f"📡 Which <b>sources</b>? Available: <code>{names}</code>\n"
        "Send a comma-separated list, or /skip to use all.",
        parse_mode="HTML",
    )
    return SOURCES


async def set_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chosen = [s.strip() for s in update.message.text.split(",") if s.strip()]
    valid = {s.name for s in all_sources()}
    context.user_data["new_filter"]["sources"] = ",".join(c for c in chosen if c in valid)
    return await _finish(update, context)


async def skip_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_filter"]["sources"] = ""
    return await _finish(update, context)


async def _finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data.get("new_filter", {})
    chat_id = update.effective_chat.id

    with session_scope() as session:
        existing = (
            session.query(SavedFilter)
            .filter(SavedFilter.chat_id == chat_id, SavedFilter.name == data.get("name", "filter"))
            .first()
        )
        if existing:
            await update.message.reply_text(
                f"⚠️ A filter named \"{data.get('name')}\" already exists. "
                "Pick another name with /newfilter."
            )
            context.user_data.pop("new_filter", None)
            return ConversationHandler.END

        saved = SavedFilter(
            chat_id=chat_id,
            name=data.get("name", "filter"),
            city=data.get("city", ""),
            min_price=data.get("min_price"),
            max_price=data.get("max_price"),
            min_rooms=data.get("min_rooms"),
            max_rooms=data.get("max_rooms"),
            require_mamad=data.get("require_mamad", False),
            require_shelter=data.get("require_shelter", False),
            sources=data.get("sources", ""),
            require_image=True,
            require_price=True,
            active=True,
        )
        session.add(saved)
        session.flush()
        summary = saved.summary()

    context.user_data.pop("new_filter", None)
    await update.message.reply_text(
        f"✅ Filter saved!\n\n{summary}\n\n"
        "It will run automatically on the schedule. Use /run to search now, "
        "or /filters to manage it.",
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_filter", None)
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("newfilter", start_new_filter)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_name)],
            CITY: [
                CommandHandler("skip", skip_city),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_city),
            ],
            PRICE: [
                CommandHandler("skip", skip_price),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_price),
            ],
            ROOMS: [
                CommandHandler("skip", skip_rooms),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_rooms),
            ],
            MAMAD: [CallbackQueryHandler(set_mamad)],
            SHELTER: [CallbackQueryHandler(set_shelter)],
            SOURCES: [
                CommandHandler("skip", skip_sources),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_sources),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
