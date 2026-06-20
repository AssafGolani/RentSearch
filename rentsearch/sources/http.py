"""Shared HTTP client for scraping Israeli sites — robots.txt aware.

``make_client`` returns a :class:`PoliteClient` that, before every request:

* fetches and caches each host's ``robots.txt`` and refuses URLs the host
  disallows for us (raising :class:`RobotsDisallowed`), and
* honors any ``Crawl-delay`` (and a small default minimum) by spacing out
  requests to the same host.

This keeps all adapters (Yad2, Madlan, generic sites) compliant by construction
— an adapter simply uses ``client.get(url)`` and never has to think about it.
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

import httpx

from ..config import settings
from .robots import RobotsRules, parse_robots

logger = logging.getLogger(__name__)

# A realistic desktop UA + Hebrew locale reduces the chance of being served a
# bot-challenge or an English fallback page. The "RentSearch" token lets sites
# identify us in their logs and lets our own robots matcher find a specific group.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 RentSearch/1.0"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/json,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Be polite even when a site sets no Crawl-delay; never hammer a host.
DEFAULT_MIN_DELAY_SECONDS = 1.0
# Cap how long we'll ever wait for crawl-delay (a huge value would stall the bot).
MAX_DELAY_SECONDS = 8.0

# host -> RobotsRules (cached for the process lifetime)
_ROBOTS_CACHE: dict[str, RobotsRules] = {}
# host -> last request monotonic timestamp
_LAST_REQUEST: dict[str, float] = {}
_LOCK = threading.Lock()


class RobotsDisallowed(Exception):
    """Raised when a URL is disallowed by the host's robots.txt."""

    def __init__(self, url: str):
        super().__init__(f"Blocked by robots.txt: {url}")
        self.url = url


def _fetch_robots(scheme: str, host: str) -> RobotsRules:
    """Fetch + parse robots.txt for a host, following Google's status-code rules.

    2xx -> parse; 4xx -> treat as allow-all; 5xx/network error -> allow-all but
    warn (so a flaky robots host can't take the whole bot down). Explicit rules
    are always honored when we can read them.
    """
    robots_url = f"{scheme}://{host}/robots.txt"
    try:
        resp = httpx.get(
            robots_url,
            headers={"User-Agent": USER_AGENT},
            timeout=10.0,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        logger.warning("robots.txt fetch failed for %s (%s); proceeding cautiously", host, exc)
        return RobotsRules(rules=[], allow_all=True)

    if 200 <= resp.status_code < 300:
        return parse_robots(resp.text, USER_AGENT)
    if 400 <= resp.status_code < 500:
        # No robots / forbidden robots -> per spec, no crawl restrictions.
        return RobotsRules(rules=[], allow_all=True)
    logger.warning("robots.txt for %s returned %s; proceeding cautiously", host, resp.status_code)
    return RobotsRules(rules=[], allow_all=True)


def get_robots(scheme: str, host: str) -> RobotsRules:
    with _LOCK:
        cached = _ROBOTS_CACHE.get(host)
        if cached is not None:
            return cached
    rules = _fetch_robots(scheme, host)
    with _LOCK:
        _ROBOTS_CACHE[host] = rules
    return rules


def _respect_crawl_delay(host: str, crawl_delay: float | None) -> None:
    delay = max(DEFAULT_MIN_DELAY_SECONDS, crawl_delay or 0.0)
    delay = min(delay, MAX_DELAY_SECONDS)
    with _LOCK:
        last = _LAST_REQUEST.get(host)
        now = time.monotonic()
        if last is not None:
            wait = delay - (now - last)
        else:
            wait = 0.0
        # Reserve our slot before sleeping so concurrent callers queue correctly.
        _LAST_REQUEST[host] = max(now, (last or now) + delay)
    if wait > 0:
        time.sleep(min(wait, MAX_DELAY_SECONDS))


class PoliteClient:
    """Thin wrapper over ``httpx.Client`` that enforces robots.txt + crawl-delay."""

    def __init__(self, client: httpx.Client, respect_robots: bool = True):
        self._client = client
        self._respect_robots = respect_robots

    def get(self, url: str, **kwargs) -> httpx.Response:
        parsed = urlparse(str(url))
        host = parsed.netloc
        path_qs = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        if self._respect_robots and host:
            rules = get_robots(parsed.scheme or "https", host)
            if not rules.can_fetch(path_qs or "/"):
                raise RobotsDisallowed(str(url))
            _respect_crawl_delay(host, rules.crawl_delay)

        # httpx applies query params from kwargs after the URL; include them in
        # the robots check too if present.
        params = kwargs.get("params")
        if self._respect_robots and host and params:
            from urllib.parse import urlencode

            merged = path_qs + ("&" if parsed.query else "?") + urlencode(params, doseq=True)
            rules = get_robots(parsed.scheme or "https", host)
            if not rules.can_fetch(merged):
                raise RobotsDisallowed(f"{url}?{urlencode(params, doseq=True)}")

        return self._client.get(url, **kwargs)

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()


def make_client(extra_headers: dict[str, str] | None = None, respect_robots: bool = True) -> PoliteClient:
    headers = dict(DEFAULT_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    proxy = settings.http_proxy_url or None
    client = httpx.Client(
        headers=headers,
        timeout=settings.request_timeout_seconds,
        follow_redirects=True,
        proxy=proxy,
    )
    return PoliteClient(client, respect_robots=respect_robots)
