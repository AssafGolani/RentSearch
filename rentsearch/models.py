"""SQLAlchemy ORM models: saved filters, seen properties, favorites.

The schema persists everything the product needs to remember between runs:

* :class:`SavedFilter`  - a user's named, reusable set of search criteria.
* :class:`SeenProperty` - every property we've ever surfaced, keyed by both its
  per-source id and its cross-source ``fingerprint`` so duplicates from
  different sources are recognized and never re-notified.
* :class:`Favorite`     - properties a user explicitly starred.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SavedFilter(Base):
    __tablename__ = "saved_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(120))

    city: Mapped[str] = mapped_column(String(120), default="")
    neighborhoods: Mapped[str] = mapped_column(String(500), default="")  # comma-separated
    property_type: Mapped[str] = mapped_column(String(60), default="")

    min_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_rooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_rooms: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_floor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    require_mamad: Mapped[bool] = mapped_column(Boolean, default=False)
    require_shelter: Mapped[bool] = mapped_column(Boolean, default=False)
    require_image: Mapped[bool] = mapped_column(Boolean, default=True)
    require_price: Mapped[bool] = mapped_column(Boolean, default=True)

    sources: Mapped[str] = mapped_column(String(300), default="")  # comma-separated; empty == all
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (UniqueConstraint("chat_id", "name", name="uq_filter_chat_name"),)

    def to_search_filter(self):
        from .sources.base import SearchFilter

        return SearchFilter(
            name=self.name,
            city=self.city,
            neighborhoods=[n.strip() for n in self.neighborhoods.split(",") if n.strip()],
            property_type=self.property_type,
            min_price=self.min_price,
            max_price=self.max_price,
            min_rooms=self.min_rooms,
            max_rooms=self.max_rooms,
            min_size=self.min_size,
            max_size=self.max_size,
            min_floor=self.min_floor,
            max_floor=self.max_floor,
            require_mamad=self.require_mamad,
            require_shelter=self.require_shelter,
            require_image=self.require_image,
            require_price=self.require_price,
            sources=[s.strip() for s in self.sources.split(",") if s.strip()],
        )

    def summary(self) -> str:
        bits = [f"<b>{self.name}</b>"]
        if self.city:
            bits.append(f"📍 {self.city}")
        price = _range(self.min_price, self.max_price)
        if price:
            bits.append(f"💰 {price} ₪")
        rooms = _range(self.min_rooms, self.max_rooms)
        if rooms:
            bits.append(f"🚪 {rooms} rooms")
        size = _range(self.min_size, self.max_size)
        if size:
            bits.append(f"📐 {size} m²")
        flags = []
        if self.require_mamad:
            flags.append('ממ"ד')
        if self.require_shelter:
            flags.append("מקלט")
        if flags:
            bits.append("🛡 " + " + ".join(flags))
        if not self.active:
            bits.append("⏸ paused")
        return " · ".join(bits)


class SeenProperty(Base):
    __tablename__ = "seen_properties"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    filter_id: Mapped[int | None] = mapped_column(ForeignKey("saved_filters.id"), nullable=True)

    global_id: Mapped[str] = mapped_column(String(200), index=True)  # source:source_id
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # cross-source dedupe key

    source: Mapped[str] = mapped_column(String(40))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", "global_id", name="uq_seen_chat_global"),
    )


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)

    global_id: Mapped[str] = mapped_column(String(200), index=True)
    payload: Mapped[str] = mapped_column(Text)  # JSON snapshot of the Listing
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", "global_id", name="uq_fav_chat_global"),
    )

    @staticmethod
    def serialize_listing(listing) -> str:
        return json.dumps(
            {
                "source": listing.source,
                "source_id": listing.source_id,
                "url": listing.url,
                "title": listing.title,
                "price": listing.price,
                "currency": listing.currency,
                "rooms": listing.rooms,
                "size_sqm": listing.size_sqm,
                "city": listing.city,
                "address": listing.address,
                "lat": listing.lat,
                "lon": listing.lon,
                "images": listing.images,
                "has_mamad": listing.has_mamad,
                "has_shelter": listing.has_shelter,
            },
            ensure_ascii=False,
        )

    def deserialize(self) -> dict:
        return json.loads(self.payload)


def _range(lo, hi) -> str:
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        return f"{_fmt(lo)}–{_fmt(hi)}"
    if lo is not None:
        return f"{_fmt(lo)}+"
    return f"≤{_fmt(hi)}"


def _fmt(n) -> str:
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return f"{n:,}" if isinstance(n, int) and n >= 1000 else str(n)
