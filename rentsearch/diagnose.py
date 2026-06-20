"""Diagnostic probe — shows exactly what each source returns.

When the bot reports "0 listings", this tells you *why*: whether a source
returned an anti-bot/challenge page, a 403, a 200 with no embedded listing data
(client-side rendered), or real results your filter then dropped.

Run:
    python -m rentsearch.diagnose                # defaults to Tel Aviv
    python -m rentsearch.diagnose "ירושלים"      # a specific city
"""
from __future__ import annotations

import logging
import sys

from .sources import all_sources
from .sources.base import SearchFilter
from .sources.http import RobotsDisallowed, make_client
from .sources.yad2 import RENT_SEARCH, SITEMAP_INDEX

# Substrings that indicate an anti-bot / challenge page rather than real content.
ANTIBOT_MARKERS = [
    "captcha", "px-captcha", "perimeterx", "_px", "human verification",
    "are you a human", "access denied", "unusual traffic", "challenge-platform",
    "cf-chl", "just a moment",
]


def _probe_url(label: str, url: str) -> None:
    try:
        with make_client() as client:
            resp = client.get(url)
        text = resp.text or ""
        has_next = "__NEXT_DATA__" in text
        has_jsonld = "application/ld+json" in text
        markers = sorted({m for m in ANTIBOT_MARKERS if m in text.lower()})
        print(f"  {label}")
        print(f"     HTTP {resp.status_code} · {len(text):,} bytes "
              f"· __NEXT_DATA__={'yes' if has_next else 'NO'} "
              f"· JSON-LD={'yes' if has_jsonld else 'no'}")
        if markers:
            print(f"     ⚠ anti-bot markers found: {markers}")
    except RobotsDisallowed as exc:
        print(f"  {label}\n     BLOCKED by robots.txt: {exc}")
    except Exception as exc:  # noqa: BLE001 - diagnostic, report everything
        print(f"  {label}\n     ERROR {type(exc).__name__}: {exc}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    city = sys.argv[1] if len(sys.argv) > 1 else "תל אביב"

    print(f"\n=== RentSearch source diagnostic (city={city!r}) ===\n")

    print("Raw HTTP probes (Yad2):")
    _probe_url("rental search page", RENT_SEARCH)
    _probe_url("shelter page (Allow rule)", f"{RENT_SEARCH}?shelter=1")
    _probe_url("realestate sitemap index", SITEMAP_INDEX)

    # A deliberately loose filter so we isolate *fetching* from *filtering*:
    # no image/price requirement, no ממ"ד, no neighborhoods.
    flt = SearchFilter(
        city=city, min_rooms=2, max_rooms=4,
        require_image=False, require_price=False,
    )

    print("\nAdapter results (loose filter — no image/price/ממ\"ד requirement):")
    for src in all_sources():
        try:
            results = src.search(flt, limit=10)
            print(f"  {src.label}: {len(results)} listings")
            if results:
                sample = results[0]
                print(f"     e.g. {sample.title!r} | price={sample.price} "
                      f"| rooms={sample.rooms} | images={len(sample.images)}")
        except RobotsDisallowed as exc:
            print(f"  {src.label}: BLOCKED by robots.txt ({exc})")
        except Exception as exc:  # noqa: BLE001
            print(f"  {src.label}: ERROR {type(exc).__name__}: {exc}")

    print("\nInterpretation:")
    print("  · HTTP 403 / anti-bot markers  -> the site is blocking automated access.")
    print("  · HTTP 200 but __NEXT_DATA__=NO -> listings are loaded client-side (JS);")
    print("    plain HTTP can't see them — a headless browser would be needed.")
    print("  · Adapter returns >0 here but the bot shows 0 -> your *filter* is too")
    print("    strict (e.g. ממ\"ד needs the listing description, which feeds omit).")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
