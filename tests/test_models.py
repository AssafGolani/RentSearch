"""Tests for the ORM models and seen-property bookkeeping."""
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rentsearch.models import Base, Favorite, SavedFilter, SeenProperty
from rentsearch.sources.base import Listing


@pytest.fixture()
def session():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    yield s
    s.close()
    os.unlink(path)


def test_saved_filter_to_search_filter(session):
    f = SavedFilter(
        chat_id=1, name="test", city="חיפה",
        min_price=4000, max_price=7000, min_rooms=3,
        require_mamad=True, sources="yad2,madlan",
    )
    session.add(f)
    session.commit()

    sf = f.to_search_filter()
    assert sf.city == "חיפה"
    assert sf.min_price == 4000
    assert sf.require_mamad is True
    assert sf.sources == ["yad2", "madlan"]
    assert sf.require_image is True  # spec default


def test_seen_property_uniqueness(session):
    s1 = SeenProperty(chat_id=1, global_id="yad2:1", fingerprint="abc", source="yad2", url="u")
    session.add(s1)
    session.commit()
    rows = session.query(SeenProperty).filter_by(chat_id=1).all()
    assert len(rows) == 1


def test_favorite_roundtrip(session):
    listing = Listing(source="yad2", source_id="1", url="http://x", title="apt",
                      price=5000, city="תל אביב", images=["http://i"])
    fav = Favorite(chat_id=1, global_id=listing.global_id,
                   payload=Favorite.serialize_listing(listing))
    session.add(fav)
    session.commit()

    loaded = session.query(Favorite).first()
    data = loaded.deserialize()
    assert data["title"] == "apt"
    assert data["price"] == 5000
    assert data["city"] == "תל אביב"


def test_filter_summary_includes_flags(session):
    f = SavedFilter(chat_id=1, name="My Search", city="ירושלים",
                    min_price=5000, max_price=8000, require_mamad=True, require_shelter=True)
    summary = f.summary()
    assert "My Search" in summary
    assert "ירושלים" in summary
    assert 'ממ"ד' in summary
    assert "מקלט" in summary
