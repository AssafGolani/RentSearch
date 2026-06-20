#!/usr/bin/env python3
"""RentSearch entrypoint — starts the Telegram bot and the periodic search job.

Usage:
    python main.py

Requires TELEGRAM_BOT_TOKEN (see .env.example).
"""
from __future__ import annotations

import logging
import sys

from rentsearch.bot.app import build_application
from rentsearch.config import settings
from rentsearch.db import init_db
from rentsearch.sites import load_generic_sources


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet down httpx request logging.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> int:
    configure_logging()
    log = logging.getLogger("rentsearch")

    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("Config error: %s", p)
        log.error("Fix the above (copy .env.example to .env) and try again.")
        return 1

    init_db()
    load_generic_sources()

    application = build_application()
    log.info("RentSearch is running. Press Ctrl+C to stop.")
    # run_polling manages the event loop, scheduler job queue and graceful shutdown.
    application.run_polling(allowed_updates=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
