"""Defensive value conversion shared by every upstream parser."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pyarrow as pa

#: UFC and most modern MMA promotions schedule five-minute rounds.
ROUND_SECONDS = 300


def mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, else an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def sequence(value: Any) -> list[Any]:
    """Return ``value`` when it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def text(value: Any) -> str | None:
    """Return a stripped non-empty string, or null."""
    if value is None or isinstance(value, bool):
        return None
    result = str(value).strip()
    return result or None


def to_int(value: Any) -> int | None:
    """Parse an integer-like API value without treating booleans as integers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return None


def to_decimal(value: Any, places: int | None = None) -> Decimal | None:
    """Parse a finite decimal, optionally quantized, accepting a trailing ``%``."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    raw = str(value).strip().removesuffix("%")
    try:
        result = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    if places is not None:
        result = result.quantize(Decimal(1).scaleb(-places))
    return result


def to_bool(value: Any) -> bool | None:
    """Return a boolean only when the API supplied one."""
    return value if isinstance(value, bool) else None


def to_timestamp(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (``2025-11-08T21:00Z`` style included) into UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def to_date(value: Any) -> date | None:
    """Parse an ISO ``YYYY-MM-DD`` date."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def clock_seconds(value: Any) -> int | None:
    """Convert an ``M:SS`` (or ``H:MM:SS``) clock string into whole seconds."""
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    if not all(part.isdigit() for part in parts) or not 1 <= len(parts) <= 3:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def fight_seconds(ending_round: int | None, ending_clock_seconds: int | None) -> int | None:
    """Total elapsed fight time assuming five-minute rounds."""
    if ending_round is None or ending_clock_seconds is None or ending_round < 1:
        return None
    return (ending_round - 1) * ROUND_SECONDS + ending_clock_seconds


_LANDED_ATTEMPTED = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def landed_attempted(value: Any) -> tuple[int | None, int | None]:
    """Split ESPN's ``landed/attempted`` display value."""
    if not isinstance(value, str):
        return None, None
    match = _LANDED_ATTEMPTED.match(value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def batch_from_rows(rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> pa.RecordBatch:
    """Build a record batch in the declared column order (projection-safe)."""
    return pa.RecordBatch.from_arrays(
        [pa.array([row.get(value.name) for row in rows], type=value.type) for value in schema],
        schema=schema,
    )
