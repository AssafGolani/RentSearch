"""Tests for the robots.txt matcher against Yad2's real rules."""
from rentsearch.sources.robots import parse_robots

# A representative subset of https://www.yad2.co.il/robots.txt (the rules that
# matter for our adapter), kept verbatim.
YAD2_ROBOTS = """User-agent: *

Sitemap: https://www.yad2.co.il/sitemaps/sitemap-index.xml

#Allow specific shelter=1 rental and sales pages
Allow: /realestate/rent?shelter=1
Allow: /realestate/forsale?shelter=1

Disallow: /admin/
Disallow: /api/

Disallow: /*?*price=
Disallow: /*?*squaremeter=
Disallow: /*?*floor=
Disallow: /*?*elevator=
Disallow: /*?*parking=
Disallow: /*?*imageOnly=
Disallow: /*?*priceOnly=
Disallow: /*?*priceDropped=
Disallow: /*?*text=
Disallow: /*?*location=

Allow: /api/sitemaps/
Allow: /sitemaps/
"""

UA = "Mozilla/5.0 RentSearch/1.0"


def _rules():
    return parse_robots(YAD2_ROBOTS, UA)


def test_shelter_page_is_allowed():
    assert _rules().can_fetch("/realestate/rent?shelter=1") is True


def test_city_only_search_is_allowed():
    # 'city=' is not in the disallow list.
    assert _rules().can_fetch("/realestate/rent?city=5000") is True


def test_rooms_search_is_allowed():
    assert _rules().can_fetch("/realestate/rent?rooms=3-4") is True


def test_price_search_is_disallowed():
    assert _rules().can_fetch("/realestate/rent?price=5000") is False


def test_squaremeter_search_is_disallowed():
    assert _rules().can_fetch("/realestate/rent?squaremeter=70") is False


def test_floor_search_is_disallowed():
    assert _rules().can_fetch("/realestate/rent?city=5000&floor=2") is False


def test_api_is_disallowed():
    assert _rules().can_fetch("/api/realestate/feed") is False


def test_item_page_is_allowed():
    # Individual listing pages are not disallowed.
    assert _rules().can_fetch("/realestate/item/abc123xyz") is True


def test_sitemaps_are_allowed():
    assert _rules().can_fetch("/sitemaps/realestate/sitemap-index-regions.xml") is True
    assert _rules().can_fetch("/api/sitemaps/anything") is True


def test_imageonly_and_priceonly_toggles_disallowed():
    # These are exactly why we enforce 'must have image/price' client-side.
    assert _rules().can_fetch("/realestate/rent?imageOnly=1") is False
    assert _rules().can_fetch("/realestate/rent?priceOnly=1") is False


def test_no_user_agent_match_defaults_allow():
    rules = parse_robots("User-agent: GoogleBot\nDisallow: /\n", UA)
    # We are not GoogleBot and there's no '*' group, so nothing restricts us.
    assert rules.can_fetch("/anything") is True
