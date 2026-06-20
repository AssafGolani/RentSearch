"""One-time interactive login for the Telegram channel source.

Reading public channels uses the Telegram *client* API, which requires a user
account login (phone number + the code Telegram sends you). This script performs
that login once and saves a reusable session file; the bot then runs
non-interactively.

Setup:
1. Get an ``api_id`` and ``api_hash`` from https://my.telegram.org (API
   development tools), and put them in ``.env`` as TELEGRAM_API_ID /
   TELEGRAM_API_HASH.
2. List the channels to monitor in ``.env`` as
   ``TELEGRAM_CHANNELS=@channel_one,@channel_two``.
3. Run:  python -m rentsearch.telegram_login
   and enter your phone number and the login code when prompted.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .config import settings


async def _main() -> int:
    from telethon import TelegramClient

    Path(settings.telegram_session_path).parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    # start() prompts for phone number, login code, and 2FA password if set.
    await client.start()
    me = await client.get_me()
    name = getattr(me, "username", None) or getattr(me, "first_name", "user")
    print(f"\n✅ Logged in as {name}.")
    print(f"   Session saved to: {settings.telegram_session_path}.session")

    channels = settings.telegram_channels
    if channels:
        print(f"   Will monitor {len(channels)} channel(s): {', '.join(channels)}")
    else:
        print("   ⚠ No channels set yet — add TELEGRAM_CHANNELS to .env.")
    await client.disconnect()
    return 0


def main() -> int:
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        print(
            "Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first "
            "(get them from https://my.telegram.org)."
        )
        return 1
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
