"""Tests for SearchFilter.matches and ממ\"ד / מקלט detection."""
from rentsearch.sources.base import Listing, SearchFilter


def _listing(**kw) -> Listing:
    base = dict(source="yad2", source_id="1", url="http://x", title="apt", images=["http://img"], price=5000)
    base.update(kw)
    return Listing(**base)


def test_requires_image_by_default():
    flt = SearchFilter()
    assert flt.matches(_listing(images=["http://img"]))
    assert not flt.matches(_listing(images=[]))


def test_requires_price_by_default():
    flt = SearchFilter()
    assert flt.matches(_listing(price=5000))
    assert not flt.matches(_listing(price=None))
    assert not flt.matches(_listing(price=0))


def test_price_range():
    flt = SearchFilter(min_price=4000, max_price=6000)
    assert flt.matches(_listing(price=5000))
    assert not flt.matches(_listing(price=3000))
    assert not flt.matches(_listing(price=7000))


def test_rooms_range():
    flt = SearchFilter(min_rooms=3, max_rooms=4)
    assert flt.matches(_listing(rooms=3.5))
    assert not flt.matches(_listing(rooms=2))
    assert not flt.matches(_listing(rooms=5))


def test_mamad_detection_from_text():
    listing = _listing(description='דירה מהממת עם ממ"ד גדול')
    assert listing.has_mamad is True
    flt = SearchFilter(require_mamad=True)
    assert flt.matches(listing)


def test_mamad_required_but_absent():
    listing = _listing(description="דירה רגילה ללא הגנה")
    assert listing.has_mamad is False
    flt = SearchFilter(require_mamad=True)
    assert not flt.matches(listing)


def test_shelter_detection_from_text():
    listing = _listing(description="בבניין יש מקלט משותף")
    assert listing.has_shelter is True
    assert SearchFilter(require_shelter=True).matches(listing)


def test_city_filter():
    listing = _listing(city="תל אביב")
    assert SearchFilter(city="תל אביב").matches(listing)
    assert not SearchFilter(city="חיפה").matches(listing)


def test_google_maps_url_uses_coords_when_available():
    listing = _listing(lat=32.08, lon=34.78)
    url = listing.google_maps_url()
    assert "32.08,34.78" in url
