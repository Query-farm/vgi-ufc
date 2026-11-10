"""ESPN-backed fighter profile, fight history, and per-fight career statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
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
from vgi_ufc.espn import (
    CAREER_STATS_SCHEMA,
    FIGHT_HISTORY_SCHEMA,
    FIGHTER_SCHEMA,
    flatten_career_stats,
    flatten_fight_history,
    flatten_fighter,
)

_FIGHTER_ID = Arg(
    0,
    arrow_type=pa.int64(),
    ge=1,
    doc="ESPN athlete id (for example 3022677 = Conor McGregor), as returned by event_bouts().",
)


@dataclass(kw_only=True)
class FighterArgs:
    """A single ESPN athlete id."""

    fighter_id: Annotated[int, _FIGHTER_ID]


_PROFILE_SQL = (
    "SELECT fighter_name, nickname, record, ko_tko_wins, submission_wins, height_in, reach_in, stance "
    "FROM ufc.main.fighter(3022677)"
)
_HISTORY_SQL = (
    "SELECT fight_number, event_time, event_name, opponent_name, result, method, ending_round "
    "FROM ufc.main.fighter_fight_history(3022677) ORDER BY fight_number"
)
_CAREER_SQL = (
    "SELECT event_name, opponent_name, result, sig_strikes_landed, sig_strikes_attempted, takedowns_landed "
    "FROM ufc.main.fighter_career_stats(3022677) ORDER BY event_time DESC"
)


class _FighterBase:
    ESTIMATE: ClassVar[int] = 1

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        return TableCardinality(estimate=cls.ESTIMATE, max=200)


@init_single_worker
@bind_fixed_schema
class FighterFunction(_FighterBase, TableFunctionGenerator[FighterArgs]):
    """One fighter's ESPN profile."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = FIGHTER_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "fighter"
        description = "One MMA fighter's profile and career record from ESPN"
        categories = ["mma", "fighters"]
        projection_pushdown = True
        tags = function_tags(
            category="fighters",
            title="Fighter Profile",
            llm=(
                "One row for an ESPN athlete id: name, nickname, date of birth, age, height, weight and "
                "reach, stance, fighting style, weight class, gym, citizenship, active flag, and "
                "professional record with KO/TKO and submission wins and losses. ESPN athlete ids come "
                "from event_bouts (fighter1_id, fighter2_id, winner_id). Unknown ids return no rows."
            ),
            md="An ESPN fighter profile. ESPN athlete ids differ from UFC feed fighter ids.",
            schema=FIGHTER_SCHEMA,
            examples=[("Conor McGregor's profile and finishing record.", _PROFILE_SQL)],
        )
        examples = [FunctionExample(sql=_PROFILE_SQL, description="Conor McGregor's profile")]

    @classmethod
    def process(cls, params: ProcessParams[FighterArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the profile."""
        response = api.fetch_athlete(params.args.fighter_id)
        emit(flatten_fighter(response.payload), params.output_schema, out, [response.ttl])


@init_single_worker
@bind_fixed_schema
class FighterFightHistoryFunction(_FighterBase, TableFunctionGenerator[FighterArgs]):
    """Every professional fight ESPN lists for a fighter."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = FIGHT_HISTORY_SCHEMA
    ESTIMATE = 20

    class Meta:
        """Function discovery metadata."""

        name = "fighter_fight_history"
        description = "A fighter's professional fight history from ESPN, most recent first"
        categories = ["mma", "fighters", "results"]
        projection_pushdown = True
        tags = function_tags(
            category="fighters",
            title="Fighter Fight History",
            llm=(
                "One row per professional fight for an ESPN athlete id, newest first (fight_number 1 = "
                "latest): event, date, promotion, opponent, result (W, L, D), method, ending round "
                "and time, and title-fight flag. Covers fights outside the UFC too."
            ),
            md="ESPN's fight history for one fighter across promotions.",
            schema=FIGHT_HISTORY_SCHEMA,
            examples=[("Conor McGregor's fight history.", _HISTORY_SQL)],
        )
        examples = [FunctionExample(sql=_HISTORY_SQL, description="Conor McGregor's fight history")]

    @classmethod
    def process(cls, params: ProcessParams[FighterArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the history."""
        response = api.fetch_athlete(params.args.fighter_id)
        emit(flatten_fight_history(response.payload), params.output_schema, out, [response.ttl])


@init_single_worker
@bind_fixed_schema
class FighterCareerStatsFunction(_FighterBase, TableFunctionGenerator[FighterArgs]):
    """Per-fight striking, clinch, and ground statistics for a fighter."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = CAREER_STATS_SCHEMA
    ESTIMATE = 15

    class Meta:
        """Function discovery metadata."""

        name = "fighter_career_stats"
        description = "A fighter's per-fight striking, clinch, takedown, and ground statistics from ESPN"
        categories = ["mma", "fighters", "fight-stats"]
        projection_pushdown = True
        tags = function_tags(
            category="fighters",
            title="Fighter Career Statistics",
            llm=(
                "One row per tracked fight for an ESPN athlete id with that fight's statistics: "
                "knockdowns, total and significant strikes landed/attempted, distance strikes by "
                "target, target shares, clinch and ground strikes, takedowns landed/attempted/slams, "
                "takedown accuracy, reversals, advances and submission attempts. SUM the columns for "
                "career totals. Only fights ESPN tracked in detail appear (mostly UFC since 2010s)."
            ),
            md=(
                "Per-fight career statistics from ESPN, enriched with event name, date, opponent and "
                "result from the fighter's profile. Aggregate with `SUM()` for career totals."
            ),
            schema=CAREER_STATS_SCHEMA,
            examples=[("Conor McGregor's striking by fight.", _CAREER_SQL)],
        )
        examples = [FunctionExample(sql=_CAREER_SQL, description="Conor McGregor's per-fight statistics")]

    @classmethod
    def process(cls, params: ProcessParams[FighterArgs], state: None, out: OutputCollector) -> None:
        """Fetch the statistics and the profile used to label each fight."""
        fighter_id = params.args.fighter_id
        stats = api.fetch_athlete_stats(fighter_id)
        profile = api.fetch_athlete(fighter_id)
        rows = flatten_career_stats(stats.payload, profile.payload, fighter_id) if stats.payload else []
        emit(rows, params.output_schema, out, [stats.ttl, profile.ttl])


FIGHTER_FUNCTIONS = [FighterFunction, FighterFightHistoryFunction, FighterCareerStatsFunction]
