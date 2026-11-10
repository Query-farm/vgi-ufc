"""The scan behind the ``current_rankings`` table (official ufc.com rankings)."""

from __future__ import annotations

from typing import ClassVar

import pyarrow as pa
from vgi.metadata import FunctionExample
from vgi.table_function import (
    ProcessParams,
    TableCardinality,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_ufc import api
from vgi_ufc.common import emit, function_tags
from vgi_ufc.rankings import RANKINGS_SCHEMA, parse_rankings

_SCAN_SQL = (
    "SELECT division, rank, fighter_name FROM ufc.main.all_current_rankings() "
    "WHERE is_champion ORDER BY division_order"
)


@init_single_worker
@bind_fixed_schema
class CurrentRankingsFunction(TableFunctionGenerator[None]):
    """Official UFC rankings backing the ``current_rankings`` table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = RANKINGS_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_current_rankings"
        description = "Official current UFC rankings from ufc.com (scan behind current_rankings)"
        categories = ["mma", "rankings"]
        projection_pushdown = True
        tags = function_tags(
            category="rankings",
            title="Current UFC Rankings (scan)",
            llm="The scan behind the current_rankings table. Prefer the table.",
            md="Official ufc.com rankings. Selecting `current_rankings` is normally clearer.",
            schema=RANKINGS_SCHEMA,
            examples=[("Current champions straight from the backing scan.", _SCAN_SQL)],
        )
        examples = [FunctionExample(sql=_SCAN_SQL, description="Current UFC champions from the backing scan")]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Thirteen lists of fifteen to sixteen fighters."""
        return TableCardinality(estimate=206, max=400)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and parse the rankings page."""
        response = api.fetch_rankings_html()
        emit(parse_rankings(response.payload), params.output_schema, out, [response.ttl])


RANKING_FUNCTIONS = [CurrentRankingsFunction]
