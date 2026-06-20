"""Periodic search job.

Runs every active saved filter on a fixed interval and pushes any new listings
to the owning chat and the broadcast channel. Used both by the bot's in-process
JobQueue and by the standalone ``rentsearch.cron`` entrypoint.
"""
from __future__ import annotations

import logging

from telegram import Bot

from .db import session_scope
from .models import SavedFilter
from .notifier import broadcast_listing, send_listing
from .search import collect_new_listings

logger = logging.getLogger(__name__)


async def run_all_filters(bot: Bot) -> int:
    """Run every active filter once. Returns the number of new listings sent."""
    total_new = 0
    with session_scope() as session:
        filters = session.query(SavedFilter).filter(SavedFilter.active.is_(True)).all()
        logger.info("Scheduler: running %d active filters", len(filters))
        for saved in filters:
            chat_id = saved.chat_id
            name = saved.name
            try:
                new_listings = collect_new_listings(saved, session)
            except Exception as exc:
                logger.exception("Filter '%s' failed: %s", name, exc)
                continue
            # Commit 'seen' rows before sending so a send crash can't cause re-notifies.
            session.commit()
            for listing in new_listings:
                try:
                    await send_listing(bot, chat_id, listing, name)
                    await broadcast_listing(bot, listing, name)
                    total_new += 1
                except Exception as exc:
                    logger.warning("Failed to send listing %s: %s", listing.global_id, exc)
    logger.info("Scheduler: sent %d new listings", total_new)
    return total_new


async def scheduled_job(context) -> None:
    """JobQueue callback wrapper."""
    await run_all_filters(context.bot)
