# RentSearch 🏠

A Telegram-based system that searches **Israeli rental properties** across
multiple sources, de-duplicates them, and notifies you the moment a new match
appears — always with a **photo**, a **price**, and a **Google Maps pin**.

Built for renters who are tired of refreshing five different sites all day.

---

## What it does

- **Searches multiple sources**: Yad2, Madlan, Facebook (Marketplace/groups),
  and any Israeli real-estate site that publishes schema.org data (HomeLess,
  WinWin, Komo, agency sites… add them in `config.yaml`, no code needed).
- **Runs automatically on an interval** (cron-style). Every active saved filter
  re-runs every `SEARCH_INTERVAL_MINUTES` and only *new* properties are sent.
- **Saved filters**: create named searches (city, price, rooms, size, floor,
  and the **ממ"ד / מקלט** flags) right from Telegram and manage them later.
- **Cross-source de-duplication**: the same apartment posted on Yad2, Madlan and
  a Facebook group is collapsed into a single notification.
- **Favorites**: tap ☆ on any property to save it; review them with `/favorites`.
- **Map pinpoint**: every property has a 🗺 button that opens its exact location
  in Google Maps (by coordinates when available, otherwise by address).
- **Only quality listings**: results are guaranteed to have **at least one image**
  and a **stated price** — listings missing either are dropped.
- **Telegram notifications**: alerts go to the user who created the filter and,
  optionally, broadcast to a channel/group for a whole team or family.
- **ממ"ד / מקלט filters**: first-class support for requiring a protected room
  (ממ"ד) and/or a bomb shelter (מקלט), detected from structured data *and* the
  free-text description.

---

## Architecture

```
                 ┌──────────────────────────────────────────────┐
                 │                  Telegram                     │
                 │   user chats  ·  optional broadcast channel   │
                 └───────────────▲───────────────▲──────────────┘
                                 │ commands       │ notifications
                         ┌───────┴────────────────┴────────┐
                         │        Telegram Bot (PTB)        │
                         │  handlers · /newfilter wizard ·  │
                         │  favorites · JobQueue (interval) │
                         └───────────────┬──────────────────┘
                                         │
                         ┌───────────────▼──────────────────┐
                         │       search orchestrator         │
                         │  query → filter → de-dup → "seen" │
                         └───┬───────────┬──────────┬────────┘
            ┌────────────────┘           │          └──────────────┐
       ┌────▼─────┐   ┌──────▼─────┐ ┌───▼──────┐         ┌─────────▼────────┐
       │  Yad2    │   │  Madlan    │ │ Facebook │   …     │ Generic (JSON-LD)│
       │ adapter  │   │  adapter   │ │ adapter  │         │  any IL RE site  │
       └──────────┘   └────────────┘ └──────────┘         └──────────────────┘
                                         │
                                  ┌──────▼──────┐
                                  │  SQLite DB  │
                                  │ filters ·   │
                                  │ seen · favs │
                                  └─────────────┘
```

Every source implements one method — `SourceAdapter.search(filter) -> [Listing]`
— and returns the same normalized `Listing` object. The rest of the system never
touches site-specific HTML/JSON, so **adding a source is self-contained**.

---

## Quick start

### 1. Create a Telegram bot
Talk to [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the token.

### 2. Configure
```bash
cp .env.example .env
# edit .env and paste TELEGRAM_BOT_TOKEN
# (optional) cp config.example.yaml config.yaml   # to add more sites
```

### 3. Install & run
```bash
pip install -r requirements.txt
python main.py
```

Then open your bot in Telegram and send `/start`.

### Run with Docker
```bash
docker compose up -d
```

---

## Using the bot

| Command | What it does |
|---|---|
| `/start`, `/help` | Show the welcome / command list |
| `/newfilter` | Step-by-step wizard to create a saved search |
| `/filters` | List your filters with **Run / Pause / Delete** buttons |
| `/run` | Search all your active filters right now |
| `/favorites` | Show properties you've starred |
| `/sources` | List the property sources being searched |

Every property card has **🔗 Open**, **🗺 Map**, and **☆ Save** buttons.

### Creating a filter
`/newfilter` walks you through: name → city → price range → rooms range →
require ממ"ד? → require מקלט? → which sources. Anything can be skipped with
`/skip`. Ranges accept `4000-7000`, `5000-` (min only), or a single number.

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | **Required.** Bot token from BotFather. |
| `TELEGRAM_CHANNEL_ID` | _(empty)_ | Optional channel/group to broadcast new properties to. |
| `SEARCH_INTERVAL_MINUTES` | `30` | How often every active filter re-runs. |
| `GOOGLE_MAPS_API_KEY` | _(empty)_ | Optional; improves pin accuracy via geocoding. |
| `DATABASE_URL` | `sqlite:///data/rentsearch.db` | SQLAlchemy database URL. |
| `HTTP_PROXY_URL` | _(empty)_ | Optional outbound proxy for scrapers. |
| `REQUEST_TIMEOUT_SECONDS` | `25` | Per-request HTTP timeout. |

### Enabling Facebook
Facebook has no public rentals API and requires a logged-in session. To enable it:
```bash
# in .env
FACEBOOK_COOKIE="c_user=...; xs=..."          # from a browser you control
FACEBOOK_SEARCH_URLS="https://www.facebook.com/marketplace/...,https://www.facebook.com/groups/.../search?q=..."
```
Use only an account you own and respect Facebook's Terms of Service.

### Adding more Israeli sites
Copy `config.example.yaml` to `config.yaml` and list any site that emits
schema.org JSON-LD listings:
```yaml
generic_sources:
  - name: homeless
    label: HomeLess
    search_url: "https://www.homeless.co.il/rent/?city={city}"
```
`{city}`, `{min_price}`, `{max_price}` are filled in from each filter.

---

## Scheduling

The bot schedules searches **internally** via the Telegram JobQueue — just run
`python main.py` and it re-runs every filter on the interval.

Prefer OS-level cron (e.g. for webhook deployments)? Use the one-shot runner:
```cron
*/30 * * * *  cd /opt/rentsearch && python -m rentsearch.cron
```

---

## How de-duplication works

1. **Exact fingerprint** — normalized address + rooms + size + price-bucket.
   Catches the same flat cross-posted to several sites.
2. **Fuzzy fallback** — for listings without a clean address (common on
   Facebook), titles are compared with token-set similarity plus a price/rooms
   sanity check.

When duplicates are found, the **best** copy is kept (most images → has
coordinates → has description → cheapest). Every surfaced property is recorded in
`seen_properties` by *both* its per-source id and its fingerprint, so it is never
notified twice — even if it later shows up on a different source.

---

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Project layout:
```
rentsearch/
  config.py          # env-based settings
  models.py          # ORM: SavedFilter, SeenProperty, Favorite
  db.py              # engine + session scope
  dedup.py           # cross-source de-duplication
  search.py          # orchestrator: query → filter → dedup → seen
  scheduler.py       # periodic / cron run of all filters
  notifier.py        # render + send listings to Telegram
  formatting.py      # HTML captions + inline keyboards
  sites.py           # load generic sources from config.yaml
  sources/           # Yad2, Madlan, Facebook, generic adapters + base
    robots.py        # robots.txt parser + longest-match matcher
    http.py          # PoliteClient: robots-aware, crawl-delay-respecting fetch
  bot/               # Telegram application, handlers, /newfilter wizard
main.py              # entrypoint (bot + interval scheduler)
```

---

## Respecting robots.txt & site rules

Every outbound request goes through a **robots.txt-aware fetch layer**
(`sources/http.py` → `PoliteClient`). Before fetching a URL it loads and caches
the host's `robots.txt`, refuses any path the site disallows for us, and spaces
out requests per the host's `Crawl-delay`. The matcher (`sources/robots.py`)
implements Google's spec — wildcards, end-anchors, and *longest-match-wins*
precedence — because the stdlib parser mishandles rules like `Disallow: /*?*price=`.

The **Yad2 adapter is built around the paths Yad2 explicitly permits**:

- It crawls the rental search page using **only allowed parameters** (`city`,
  `rooms`, and `shelter=1`), never the disallowed ones (`price`, `squaremeter`,
  `floor`, `imageOnly`, …). Those criteria — including price, size and **ממ"ד** —
  are applied **client-side** instead.
- It uses the explicitly-allowed `Allow: /realestate/rent?shelter=1` page as the
  fast path for **מקלט** searches, and the published **sitemaps** for discovery.
- It reads listings from the page's embedded `__NEXT_DATA__`, never the
  disallowed `/api/` endpoints.

If Yad2 ever tightens a rule, the fetch layer simply returns *no results from
Yad2* (logged) rather than making a disallowed request. The same protection
covers Madlan and any generic source you add.

---

## Notes & limitations

- Scrapers depend on third-party site structure, which changes over time. The
  adapters are written defensively (a schema change degrades gracefully rather
  than crashing the run), but a source may occasionally need its parser updated.
- Yad2 expects a **numeric city code** for the `city` parameter; the adapter
  passes your value through and relies on the client-side city match as a
  backstop, so broad results still get narrowed correctly.
- Use responsibly: keep the search interval reasonable, respect each site's
  Terms of Service, and consider an Israeli residential proxy only if you hit
  rate limits at higher volumes.
