"""Functions over UFC's official live-data feed: cards, results, and fight statistics."""

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
from vgi_ufc.feed import (
    CARD_FIGHTER_SCHEMA,
    FEED_EVENT_SCHEMA,
    FIGHT_CARD_SCHEMA,
    FIGHT_RESULT_SCHEMA,
    FIGHT_STATS_SCHEMA,
    ROUND_STATS_SCHEMA,
    SCORECARD_SCHEMA,
    flatten_card_fighters,
    flatten_feed_event,
    flatten_fight_card,
    flatten_fight_results,
    flatten_fight_stats,
    flatten_round_stats,
    flatten_scorecards,
)

MAX_SCAN_SPAN = 100

_EVENT_ID = Arg(
    0,
    arrow_type=pa.int32(),
    ge=1,
    doc="UFC live-data event id (sequential, e.g. 1291 = 2025-11-08); find ids with feed_events().",
)
_FIGHT_ID = Arg(
    0,
    arrow_type=pa.int32(),
    ge=1,
    doc="UFC live-data fight id, from fight_card() or fight_results().",
)


@dataclass(kw_only=True)
class EventArgs:
    """A single UFC feed event id."""

    event_id: Annotated[int, _EVENT_ID]


@dataclass(kw_only=True)
class FightArgs:
    """A single UFC feed fight id."""

    fight_id: Annotated[int, _FIGHT_ID]


@dataclass(kw_only=True)
class ScanArgs:
    """An inclusive range of UFC feed event ids."""

    first_id: Annotated[int, Arg(0, arrow_type=pa.int32(), ge=1, doc="First UFC feed event id to probe.")]
    last_id: Annotated[
        int,
        Arg(
            1, arrow_type=pa.int32(), ge=1, doc=f"Last UFC feed event id to probe (span <= {MAX_SCAN_SPAN})."
        ),
    ]


_SCAN_SQL = (
    "SELECT event_id, event_name, start_time, status, fight_count "
    "FROM ufc.main.feed_events(1285, 1300) ORDER BY start_time"
)
_CARD_SQL = (
    "SELECT fight_order, card_segment, weight_class, red_fighter_name, blue_fighter_name "
    "FROM ufc.main.fight_card(1291) ORDER BY fight_order"
)
_FIGHTERS_SQL = (
    "SELECT fighter_name, corner, outcome, height_in, reach_in, stance, weigh_in_lbs "
    "FROM ufc.main.card_fighters(1291) ORDER BY fight_order, corner DESC"
)
_RESULTS_SQL = (
    "SELECT fight_order, winner_name, loser_name, method, ending_round, ending_time "
    "FROM ufc.main.fight_results(1291) ORDER BY fight_order"
)
_SCORECARDS_SQL = (
    "SELECT judge_name, round_number, red_fighter_name, red_score, blue_fighter_name, blue_score "
    "FROM ufc.main.fight_scorecards(12000) ORDER BY judge_name, round_number"
)
_STATS_SQL = (
    "SELECT fighter_name, knockdowns, sig_strikes_landed, sig_strikes_attempted, "
    "sig_strike_accuracy_pct, takedowns_landed, control_seconds "
    "FROM ufc.main.fight_stats(12000)"
)
_ROUNDS_SQL = (
    "SELECT round_number, fighter_name, sig_strikes_landed, sig_strikes_attempted, sig_head_landed "
    "FROM ufc.main.fight_round_stats(12000) ORDER BY round_number, corner DESC"
)


def _scan(first_id: int, last_id: int) -> tuple[list[dict], list[int]]:
    if last_id < first_id:
        raise ValueError("last_id must be greater than or equal to first_id")
    if last_id - first_id + 1 > MAX_SCAN_SPAN:
        raise ValueError(f"feed_events scans at most {MAX_SCAN_SPAN} ids per call")
    results = api.fetch_feed_events(range(first_id, last_id + 1))
    rows = [row for result in results for row in flatten_feed_event(result.payload)]
    return rows, [result.ttl for result in results]


@init_single_worker
@bind_fixed_schema
class FeedEventsFunction(TableFunctionGenerator[ScanArgs]):
    """Probe a range of UFC feed event ids and list the events found."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = FEED_EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "feed_events"
        description = "List UFC live-data feed events whose ids fall in a range (event-id discovery)"
        categories = ["mma", "ufc-feed", "events"]
        projection_pushdown = True
        tags = function_tags(
            category="fight-cards",
            title="UFC Feed Event Lookup",
            llm=(
                "UFC's official live-data feed numbers events with sequential integers that cannot be "
                "searched by name. feed_events(first_id, last_id) probes an inclusive id range (at "
                f"most {MAX_SCAN_SPAN} ids) and returns one row per existing event with name, start "
                "time, status, venue and fight count; missing ids are skipped. Anchors: 1252 = UFC "
                "315 (2025-05-10), 1291 = 2025-11-08, 1320 = 2026-07-18, 1343 = 2026-11-07, 1350 = UFC "
                "336 (2027-01-30). Ids are roughly but not strictly chronological, so scan a window "
                "around the date you want and filter by event_name or start_time."
            ),
            md=(
                "Event-id discovery for the UFC feed. Each id in the range is one upstream request "
                "(cached), so keep ranges tight. Use the returned `event_id` with `fight_card()`, "
                "`card_fighters()` and `fight_results()`."
            ),
            schema=FEED_EVENT_SCHEMA,
            examples=[("Find UFC feed events with ids 1285-1300.", _SCAN_SQL)],
        )
        examples = [FunctionExample(sql=_SCAN_SQL, description="Find UFC feed events with ids 1285-1300")]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """At most one row per probed id."""
        return TableCardinality(estimate=20, max=MAX_SCAN_SPAN)

    @classmethod
    def process(cls, params: ProcessParams[ScanArgs], state: None, out: OutputCollector) -> None:
        """Probe every id in the range."""
        rows, ttls = _scan(params.args.first_id, params.args.last_id)
        rows.sort(key=lambda row: row["event_id"])
        emit(rows, params.output_schema, out, ttls)


class _EventBase:
    FLATTEN: ClassVar[staticmethod]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        return TableCardinality(estimate=13, max=40)

    @classmethod
    def process(cls, params: ProcessParams[EventArgs], state: None, out: OutputCollector) -> None:
        response = api.fetch_feed_event(params.args.event_id)
        emit(cls.FLATTEN(response.payload), params.output_schema, out, [response.ttl])


class _FightBase:
    FLATTEN: ClassVar[staticmethod]
    ESTIMATE: ClassVar[int] = 2

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        return TableCardinality(estimate=cls.ESTIMATE, max=60)

    @classmethod
    def process(cls, params: ProcessParams[FightArgs], state: None, out: OutputCollector) -> None:
        response = api.fetch_feed_fight(params.args.fight_id)
        emit(cls.FLATTEN(response.payload), params.output_schema, out, [response.ttl])


@init_single_worker
@bind_fixed_schema
class FightCardFunction(_EventBase, TableFunctionGenerator[EventArgs]):
    """The fight card for one UFC feed event."""

    FIXED_SCHEMA = FIGHT_CARD_SCHEMA
    FLATTEN = staticmethod(flatten_fight_card)

    class Meta:
        """Function discovery metadata."""

        name = "fight_card"
        description = "Official UFC fight card for one event: one row per fight with both corners"
        categories = ["mma", "ufc-feed", "fight-cards"]
        projection_pushdown = True
        tags = function_tags(
            category="fight-cards",
            title="UFC Fight Card",
            llm=(
                "One row per fight on a UFC event from UFC's official feed: fight_id, running order "
                "(fight_order 1 = main event), card segment (Main, Prelims1, Prelims2), weight class, "
                "scheduled rounds, referee, and red and blue corner fighter ids, names and records. "
                "Takes a UFC feed event id (see feed_events). Use fight_results for outcomes and "
                "fight_stats / fight_round_stats with a fight_id for statistics."
            ),
            md="The official card for a UFC event, both corners per fight. Unknown ids return no rows.",
            schema=FIGHT_CARD_SCHEMA,
            examples=[("The card for UFC Fight Night on 2025-11-08 (feed id 1291).", _CARD_SQL)],
        )
        examples = [FunctionExample(sql=_CARD_SQL, description="The card for UFC feed event 1291")]


@init_single_worker
@bind_fixed_schema
class CardFightersFunction(_EventBase, TableFunctionGenerator[EventArgs]):
    """Fighter bios and outcomes for one UFC feed event."""

    FIXED_SCHEMA = CARD_FIGHTER_SCHEMA
    FLATTEN = staticmethod(flatten_card_fighters)

    class Meta:
        """Function discovery metadata."""

        name = "card_fighters"
        description = "Every fighter on a UFC event card with record, physical attributes, and outcome"
        categories = ["mma", "ufc-feed", "fight-cards", "fighters"]
        projection_pushdown = True
        tags = function_tags(
            category="fight-cards",
            title="UFC Card Fighters",
            llm=(
                "One row per fighter per fight on a UFC feed event: corner, outcome (Win, Loss, Draw, "
                "NC), record at the time, date of birth, age, stance, height and reach in inches, "
                "weigh-in weight in pounds, birthplace, training location, Performance of the Night "
                "bonus, and ufc.com athlete link. Takes a UFC feed event id."
            ),
            md="Fighter-grain detail for a UFC card from the official feed.",
            schema=CARD_FIGHTER_SCHEMA,
            examples=[("Size and stance of every fighter on feed event 1291.", _FIGHTERS_SQL)],
        )
        examples = [FunctionExample(sql=_FIGHTERS_SQL, description="Fighters on UFC feed event 1291")]


@init_single_worker
@bind_fixed_schema
class FightResultsFunction(_EventBase, TableFunctionGenerator[EventArgs]):
    """Official results for one UFC feed event."""

    FIXED_SCHEMA = FIGHT_RESULT_SCHEMA
    FLATTEN = staticmethod(flatten_fight_results)

    class Meta:
        """Function discovery metadata."""

        name = "fight_results"
        description = "Official UFC results for one event: winner, method, round, time, judges, bonuses"
        categories = ["mma", "ufc-feed", "results"]
        projection_pushdown = True
        tags = function_tags(
            category="results",
            title="UFC Fight Results",
            llm=(
                "One row per fight on a UFC feed event with the official result: winner and loser "
                "(UFC fighter ids and names), outcome (win, Draw, NC), method (KO/TKO, Submission, "
                "Decision - Unanimous/Split/Majority), ending round and time, total fight seconds, "
                "finishing strike/target/position or submission hold, judges' totals winner-first, "
                "Fight of the Night and Performance of the Night bonuses, and referee. Rows exist "
                "before the event with null result columns."
            ),
            md=(
                "Official UFC results for a card. `judges_scores` lists each judge's total as "
                "winner-loser; per-round scoring is in `fight_scorecards(fight_id)`."
            ),
            schema=FIGHT_RESULT_SCHEMA,
            examples=[("Results of UFC feed event 1291.", _RESULTS_SQL)],
        )
        examples = [FunctionExample(sql=_RESULTS_SQL, description="Results of UFC feed event 1291")]


@init_single_worker
@bind_fixed_schema
class FightScorecardsFunction(_FightBase, TableFunctionGenerator[FightArgs]):
    """Round-by-round judges' scorecards for one UFC fight."""

    FIXED_SCHEMA = SCORECARD_SCHEMA
    FLATTEN = staticmethod(flatten_scorecards)
    ESTIMATE = 9

    class Meta:
        """Function discovery metadata."""

        name = "fight_scorecards"
        description = "Round-by-round judges' scores for one UFC fight that went to a decision"
        categories = ["mma", "ufc-feed", "results"]
        projection_pushdown = True
        tags = function_tags(
            category="results",
            title="UFC Judges' Scorecards",
            llm=(
                "One row per judge per round for a UFC feed fight_id, with the red and blue corner "
                "scores under the 10-point must system. Finishes have no scorecards and return no rows. "
                "Sum red_score and blue_score by judge for the judge's total."
            ),
            md="Per-round judging for a decision. Finished fights return an empty result.",
            schema=SCORECARD_SCHEMA,
            examples=[("How each judge scored every round of fight 12000.", _SCORECARDS_SQL)],
        )
        examples = [FunctionExample(sql=_SCORECARDS_SQL, description="Judges' round scores for fight 12000")]


@init_single_worker
@bind_fixed_schema
class FightStatsFunction(_FightBase, TableFunctionGenerator[FightArgs]):
    """Whole-fight statistics for both fighters."""

    FIXED_SCHEMA = FIGHT_STATS_SCHEMA
    FLATTEN = staticmethod(flatten_fight_stats)

    class Meta:
        """Function discovery metadata."""

        name = "fight_stats"
        description = "Official UFC whole-fight statistics for both fighters in one fight"
        categories = ["mma", "ufc-feed", "fight-stats"]
        projection_pushdown = True
        tags = function_tags(
            category="fight-stats",
            title="UFC Fight Statistics",
            llm=(
                "Two rows (one per fighter) of official UFC totals for a fight_id: knockdowns, total "
                "and significant strikes landed/attempted, significant strike accuracy, significant "
                "strikes by target (head, body, leg) and position (distance, clinch, ground), "
                "takedowns, takedown accuracy, reversals, submission attempts, and control, distance, "
                "clinch and ground time in seconds."
            ),
            md="Whole-fight totals from UFC's official feed. Use `fight_round_stats()` for each round.",
            schema=FIGHT_STATS_SCHEMA,
            examples=[("Striking and grappling totals for fight 12000.", _STATS_SQL)],
        )
        examples = [FunctionExample(sql=_STATS_SQL, description="Fight totals for fight 12000")]


@init_single_worker
@bind_fixed_schema
class FightRoundStatsFunction(_FightBase, TableFunctionGenerator[FightArgs]):
    """Round-by-round statistics for both fighters."""

    FIXED_SCHEMA = ROUND_STATS_SCHEMA
    FLATTEN = staticmethod(flatten_round_stats)
    ESTIMATE = 6

    class Meta:
        """Function discovery metadata."""

        name = "fight_round_stats"
        description = "Official UFC per-round statistics for both fighters in one fight"
        categories = ["mma", "ufc-feed", "fight-stats"]
        projection_pushdown = True
        tags = function_tags(
            category="fight-stats",
            title="UFC Round-by-Round Statistics",
            llm=(
                "One row per fighter per round for a UFC fight_id with the same statistics as "
                "fight_stats (knockdowns, significant strikes by target and position, takedowns, "
                "control time and more), so momentum can be compared round by round."
            ),
            md="Per-round statistics from UFC's official feed, sorted by round then corner.",
            schema=ROUND_STATS_SCHEMA,
            examples=[("Significant strikes per round in fight 12000.", _ROUNDS_SQL)],
        )
        examples = [FunctionExample(sql=_ROUNDS_SQL, description="Per-round strikes for fight 12000")]


FIGHT_FUNCTIONS = [
    FeedEventsFunction,
    FightCardFunction,
    CardFightersFunction,
    FightResultsFunction,
    FightScorecardsFunction,
    FightStatsFunction,
    FightRoundStatsFunction,
]
