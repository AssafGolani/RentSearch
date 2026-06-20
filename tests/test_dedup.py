"""Tests for cross-source de-duplication."""
from rentsearch.dedup import deduplicate
from rentsearch.sources.base import Listing


def _l(source, sid, **kw):
    base = dict(
        source=source, source_id=sid, url=f"http://{source}/{sid}",
        title="דירת 3 חדרים ברחוב דיזנגוף 100 תל אביב",
        city="תל אביב", street="דיזנגוף 100", neighborhood="מרכז",
        price=6000, rooms=3.0, size_sqm=70, images=["http://img1"],
    )
    base.update(kw)
    return Listing(**base)


def test_same_property_across_sources_is_collapsed():
    a = _l("yad2", "1")
    b = _l("madlan", "2")  # same address/rooms/size/price -> same fingerprint
    result = deduplicate([a, b])
    assert len(result) == 1


def test_keeps_copy_with_more_images():
    a = _l("yad2", "1", images=["http://img1"])
    b = _l("madlan", "2", images=["http://img1", "http://img2", "http://img3"])
    result = deduplicate([a, b])
    assert len(result) == 1
    assert result[0].source == "madlan"  # more images wins


def test_different_properties_are_kept():
    a = _l("yad2", "1", street="דיזנגוף 100", price=6000)
    b = _l("yad2", "2", street="אבן גבירול 50", price=8000, title="דירה ברחוב אבן גבירול 50")
    result = deduplicate([a, b])
    assert len(result) == 2


def test_fuzzy_dedup_without_clean_address():
    # No structured address -> weak fingerprint -> fuzzy fallback should still merge.
    a = Listing(source="facebook", source_id="1", url="http://fb/1",
                title="להשכרה דירת 3 חדרים מהממת במרכז תל אביב", price=6000, rooms=3.0,
                images=["http://i"])
    b = Listing(source="yad2", source_id="9", url="http://y/9",
                title="דירת 3 חדרים מהממת במרכז תל אביב להשכרה", price=6050, rooms=3.0,
                images=["http://i"])
    result = deduplicate([a, b])
    assert len(result) == 1
