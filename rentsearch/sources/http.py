"""Shared HTTP client with sane defaults for scraping Israeli sites."""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# A realistic desktop UA + Hebrew locale reduces the chance of being served a
# bot-challenge or an English fallback page.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}


def make_client(extra_headers: dict[str, str] | None = None) -> httpx.Client:
    headers = dict(DEFAULT_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    proxy = settings.http_proxy_url or None
    return httpx.Client(
        headers=headers,
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        proxy=proxy,
    )
