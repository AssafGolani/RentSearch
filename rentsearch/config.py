"""Application configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_channel_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHANNEL_ID", ""))
    search_interval_minutes: int = field(default_factory=lambda: _get_int("SEARCH_INTERVAL_MINUTES", 30))
    google_maps_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY", ""))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/rentsearch.db"))
    http_proxy_url: str = field(default_factory=lambda: os.getenv("HTTP_PROXY_URL", ""))
    request_timeout_seconds: int = field(default_factory=lambda: _get_int("REQUEST_TIMEOUT_SECONDS", 25))

    # --- Telegram channel source (MTProto / Telethon) ---
    telegram_api_id: int = field(default_factory=lambda: _get_int("TELEGRAM_API_ID", 0))
    telegram_api_hash: str = field(default_factory=lambda: os.getenv("TELEGRAM_API_HASH", ""))
    telegram_channels_raw: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHANNELS", ""))
    telegram_session_path: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_SESSION_PATH", "data/telethon")
    )

    @property
    def telegram_channels(self) -> list[str]:
        return [c.strip().lstrip("@") for c in self.telegram_channels_raw.split(",") if c.strip()]

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems (empty == OK)."""
        problems: list[str] = []
        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is not set - the bot cannot start.")
        if self.search_interval_minutes < 1:
            problems.append("SEARCH_INTERVAL_MINUTES must be >= 1.")
        return problems

    def ensure_data_dir(self) -> None:
        """Make sure the sqlite data directory exists."""
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "", 1)
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
