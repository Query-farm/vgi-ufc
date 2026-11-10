"""Tests for defensive value conversion."""

from datetime import UTC, date, datetime
from decimal import Decimal

from vgi_ufc import convert


def test_integers_and_text() -> None:
    assert convert.to_int("12") == 12
    assert convert.to_int(12.0) == 12
    assert convert.to_int(12.5) is None
    assert convert.to_int(True) is None
    assert convert.to_int("x") is None
    assert convert.text("  a ") == "a"
    assert convert.text("   ") is None
    assert convert.text(False) is None


def test_decimals() -> None:
    assert convert.to_decimal("45.45%") == Decimal("45.45")
    assert convert.to_decimal(72.5, 1) == Decimal("72.5")
    assert convert.to_decimal("NaN") is None
    assert convert.to_decimal("abc") is None
    assert convert.to_decimal("") is None


def test_dates_and_times() -> None:
    assert convert.to_timestamp("2025-11-08T21:00Z") == datetime(2025, 11, 8, 21, tzinfo=UTC)
    assert convert.to_timestamp("2026-11-07T22:00:00.000+00:00") == datetime(2026, 11, 7, 22, tzinfo=UTC)
    assert convert.to_timestamp("2026-01-01T00:00:00") == datetime(2026, 1, 1, tzinfo=UTC)
    assert convert.to_timestamp("garbage") is None
    assert convert.to_date("1997-08-20") == date(1997, 8, 20)
    assert convert.to_date("nope") is None
    assert convert.to_date(None) is None


def test_clocks_and_pairs() -> None:
    assert convert.clock_seconds("4:59") == 299
    assert convert.clock_seconds("1:02:03") == 3723
    assert convert.clock_seconds("-") is None
    assert convert.clock_seconds("") is None
    assert convert.fight_seconds(3, 300) == 900
    assert convert.fight_seconds(None, 10) is None
    assert convert.fight_seconds(0, 10) is None
    assert convert.landed_attempted("5/8") == (5, 8)
    assert convert.landed_attempted("5") == (None, None)
    assert convert.landed_attempted(None) == (None, None)
    assert convert.to_bool("true") is None
    assert convert.mapping([]) == {}
    assert convert.sequence({}) == []
