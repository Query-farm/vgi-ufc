"""Helpers shared by every UFC table function."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

import pyarrow as pa
from vgi.cache_control import CacheControl
from vgi_rpc.rpc import OutputCollector

from vgi_ufc.convert import batch_from_rows
from vgi_ufc.meta import result_columns_schema

PROVIDER = "ufc"


def cache_control(ttls: Iterable[int]) -> CacheControl | None:
    """Advertise the shortest lifetime among the upstream documents used."""
    values = [ttl for ttl in ttls if ttl > 0]
    if not values:
        return None
    ttl = min(values)
    return CacheControl(ttl=ttl, stale_if_error=max(ttl, 300))


def emit(
    rows: Sequence[dict[str, Any]], output_schema: pa.Schema, out: OutputCollector, ttls: Iterable[int]
) -> None:
    """Emit one batch in the bound output schema and finish the stream."""
    out.emit(batch_from_rows(rows, output_schema), cache_control=cache_control(ttls))
    out.finish()


def function_tags(
    *,
    category: str,
    title: str,
    llm: str,
    md: str,
    schema: pa.Schema,
    examples: Sequence[tuple[str, str]],
) -> dict[str, str]:
    """Build the standard discovery tags for a table function."""
    return {
        "provider": PROVIDER,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": llm,
        "vgi.doc_md": md,
        "vgi.example_queries": json.dumps([{"description": d, "sql": s} for d, s in examples]),
    }
