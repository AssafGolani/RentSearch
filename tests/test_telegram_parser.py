"""Tests for the Telegram rental-post text parser."""
from rentsearch.sources.telegram_channels import (
    looks_like_listing,
    parse_message_fields,
    parse_price,
    parse_rooms,
    parse_size,
)

SAMPLE = """להשכרה דירת 3 חדרים ברחוב דיזנגוף תל אביב
דירה משופצת עם ממ"ד ומרפסת שמש
קומה 2, 70 מ"ר
מחיר: 6,500 ש"ח לחודש
לפרטים: 050-1234567
"""


def test_parse_price_with_currency():
    assert parse_price('מחיר 6,500 ש"ח') == 6500
    assert parse_price("5500₪") == 5500
    assert parse_price("השכרה 7200 שח לחודש") == 7200


def test_parse_price_ignores_phone_numbers():
    # 0501234567 is not in the plausible rent range and has no currency token.
    assert parse_price("טל 050-1234567") is None


def test_parse_price_none_when_absent():
    assert parse_price("דירה יפה במרכז") is None


def test_parse_rooms():
    assert parse_rooms("דירת 3 חדרים") == 3.0
    assert parse_rooms("2.5 חד'") == 2.5
    assert parse_rooms("4 חד׳") == 4.0


def test_parse_size():
    assert parse_size('70 מ"ר') == 70
    assert parse_size("100 מטר") == 100


def test_parse_message_fields_full():
    fields = parse_message_fields(SAMPLE)
    assert fields["price"] == 6500
    assert fields["rooms"] == 3.0
    assert fields["size_sqm"] == 70
    assert fields["has_mamad"] is True
    assert fields["has_shelter"] is False
    assert "דיזנגוף" in fields["title"]


def test_looks_like_listing():
    assert looks_like_listing(SAMPLE) is True
    assert looks_like_listing("מחפש שותף לדירה") is False  # no rent+price/rooms combo
    assert looks_like_listing("") is False


def test_shelter_detection():
    fields = parse_message_fields("להשכרה דירה עם מקלט בבניין, 4 חדרים")
    assert fields["has_shelter"] is True
