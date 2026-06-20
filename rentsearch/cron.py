"""Standalone one-shot search runner for external schedulers (system cron, k8s).

Runs every active filter once, sends notifications, then exits. Use this instead
of the in-process JobQueue when you prefer an OS-level cron entry, e.g.:

    */30 * * * *  cd /opt/rentsearch && python -m rentsearch.cron

The bot (main.py) already runs this on an interval internally, so you only need
this if you run the bot in webhook mode or want fully external scheduling.
"""
from __future__ import annotations

import asyncio
import logging

from telegram import Bot

from .config import settings
from .db import init_db
from .scheduler import run_all_filters
from .sites import load_generic_sources


async def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("rentsearch.cron")

    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("Config error: %s", p)
        return 1

    init_db()
    load_generic_sources()

    bot = Bot(token=settings.telegram_bot_token)
    async with bot:
        sent = await run_all_filters(bot)
    log.info("Cron run complete: %d new listings sent.", sent)
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
