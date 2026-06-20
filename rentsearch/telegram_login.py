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
    print("\nLog in with your PERSONAL Telegram account (the one that is a member")
    print("of the rental channels). Enter your phone number in international format,")
    print("e.g. +9725XXXXXXXX — do NOT enter the bot token here.\n")
    # Force the user-login path with an explicit phone prompt, so a bot token
    # can't accidentally be used (which would create an unusable bot session).
    await client.start(phone=lambda: input("Phone number: "))

    me = await client.get_me()
    if getattr(me, "bot", False):
        print("\n❌ This session is a BOT account, which cannot read channel history.")
        print("   Delete the session file below and run this again, entering your")
        print(f"   personal phone number instead:\n   {settings.telegram_session_path}.session")
        await client.disconnect()
        return 1

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
