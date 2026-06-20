"""Build and configure the Telegram Application."""
from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.error import Conflict, NetworkError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from ..config import settings
from ..scheduler import scheduled_job
from . import handlers
from .conversation import build_conversation_handler

logger = logging.getLogger(__name__)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler: keep the log readable, never crash the bot."""
    err = context.error
    if isinstance(err, Conflict):
        # Another process is polling getUpdates with the same token.
        logger.error(
            "Telegram Conflict: another instance of this bot is already running "
            "with the same token. Stop the other process (only ONE instance may "
            "poll at a time), or use a separate token."
        )
        return
    if isinstance(err, (NetworkError, TimedOut)):
        logger.warning("Telegram network issue (will retry): %s", err)
        return
    logger.exception("Unhandled error while processing an update: %s", err)


def build_application() -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()

    # /newfilter conversation (registered first so its states take priority).
    application.add_handler(build_conversation_handler())

    # Commands
    application.add_handler(CommandHandler("start", handlers.cmd_start))
    application.add_handler(CommandHandler("help", handlers.cmd_help))
    application.add_handler(CommandHandler("filters", handlers.cmd_filters))
    application.add_handler(CommandHandler("run", handlers.cmd_run))
    application.add_handler(CommandHandler("favorites", handlers.cmd_favorites))
    application.add_handler(CommandHandler("sources", handlers.cmd_sources))

    # Inline button callbacks
    application.add_handler(CallbackQueryHandler(handlers.on_favorite, pattern=r"^fav:"))
    application.add_handler(CallbackQueryHandler(handlers.on_run_filter, pattern=r"^runf:"))
    application.add_handler(CallbackQueryHandler(handlers.on_toggle_filter, pattern=r"^togglef:"))
    application.add_handler(CallbackQueryHandler(handlers.on_delete_filter, pattern=r"^delf:"))

    # Graceful error handling (tames the getUpdates Conflict / network spam).
    application.add_error_handler(_on_error)

    # Periodic search job (cron-style interval).
    interval = timedelta(minutes=settings.search_interval_minutes)
    if application.job_queue is not None:
        application.job_queue.run_repeating(
            scheduled_job,
            interval=interval,
            first=timedelta(seconds=30),
            name="rentsearch-periodic",
        )
        logger.info("Scheduled periodic search every %s minutes", settings.search_interval_minutes)
    else:
        logger.warning("JobQueue unavailable; install python-telegram-bot[job-queue]")

    return application
