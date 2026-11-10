"""ESPN-backed event calendar and fightcenter bout functions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
from vgi_ufc.espn import BOUT_SCHEMA, EVENT_SCHEMA, LEAGUES, flatten_bouts, flatten_events

_LEAGUE = Arg(
    "league",
    default="ufc",
    arrow_type=pa.string(),
    choices=LEAGUES,
    doc="ESPN league slug: ufc (default), pfl, or bellator (Bellator events end in 2024).",
)


def current_year() -> int:
    """The current calendar year in UTC."""
    return datetime.now(UTC).year


@dataclass(kw_only=True)
class EventsArgs:
    """Arguments accepted by ``events``."""

    season: Annotated[
        int | None,
        Arg(
            "season",
            default=None,
            arrow_type=pa.int32(),
            ge=1993,
            le=2100,
            doc="Calendar year. NULL selects the current year.",
        ),
    ]
    league: Annotated[str, _LEAGUE]


@dataclass(kw_only=True)
class BoutsArgs:
    """Arguments accepted by ``event_bouts``."""

    espn_event_id: Annotated[
        int,
        Arg(0, arrow_type=pa.int64(), ge=1, doc="ESPN event identifier, from events() or upcoming_events."),
    ]
    league: Annotated[str, _LEAGUE]


_EVENTS_SQL = (
    "SELECT event_id, event_name, start_time, city, country, bout_count "
    "FROM ufc.main.events(season := 2025) ORDER BY start_time"
)
_PFL_SQL = (
    "SELECT event_id, event_name, start_time, event_state "
    "FROM ufc.main.events(season := 2026, league := 'pfl') ORDER BY start_time"
)
_BOUTS_SQL = (
    "SELECT match_number, card_segment, weight_class, winner_name, method, ending_round, ending_time "
    "FROM ufc.main.event_bouts(600057024) ORDER BY match_number"
)
_UPCOMING_SQL = (
    "SELECT event_id, event_name, start_time, city, country, bout_count "
    "FROM ufc.main.upcoming_events ORDER BY start_time"
)
_SEASON_SQL = (
    "SELECT event_id, event_name, start_time, event_state "
    "FROM ufc.main.current_season_events ORDER BY start_time"
)


def _season_rows(league: str, season: int) -> tuple[list[dict], int]:
    response = api.fetch_scoreboard(league, season)
    return flatten_events(response.payload, league), response.ttl


@init_single_worker
@bind_fixed_schema
class EventsFunction(TableFunctionGenerator[EventsArgs]):
    """ESPN's event calendar for one MMA promotion and year."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "events"
        description = "MMA event calendar (UFC, PFL, or Bellator) for one year, from ESPN"
        categories = ["mma", "events"]
        projection_pushdown = True
        tags = function_tags(
            category="events",
            title="Event Calendar",
            llm=(
                "One row per event for a promotion and calendar year from ESPN: event_id, name, "
                "start time, venue, status and bout count. league => 'ufc' (default), 'pfl', or "
                "'bellator'. Use event_bouts(event_id) for the bouts and results. ESPN event ids are "
                "not UFC feed ids; for official UFC fight stats find the feed id with feed_events()."
            ),
            md=(
                "ESPN's calendar of events for one MMA promotion and year. `event_state` is `pre`, `in`, "
                "or `post`. Pass `event_id` to `event_bouts()` for that card's bouts and results."
            ),
            schema=EVENT_SCHEMA,
            examples=[
                ("Every UFC event in 2025.", _EVENTS_SQL),
                ("The 2026 PFL calendar.", _PFL_SQL),
            ],
        )
        examples = [FunctionExample(sql=_EVENTS_SQL, description="Every UFC event in 2025")]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """UFC runs about 40-55 events a year."""
        return TableCardinality(estimate=50, max=200)

    @classmethod
    def process(cls, params: ProcessParams[EventsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the calendar."""
        season = params.args.season if params.args.season is not None else current_year()
        rows, ttl = _season_rows(params.args.league, season)
        emit(rows, params.output_schema, out, [ttl])


@init_single_worker
@bind_fixed_schema
class EventBoutsFunction(TableFunctionGenerator[BoutsArgs]):
    """Bouts and results for one ESPN event (fightcenter)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = BOUT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "event_bouts"
        description = "Bouts and results for one ESPN MMA event (UFC, PFL, or Bellator)"
        categories = ["mma", "events", "results"]
        projection_pushdown = True
        tags = function_tags(
            category="events",
            title="Event Bouts and Results",
            llm=(
                "One row per bout for an ESPN event_id (from events, upcoming_events or "
                "current_season_events): running order (match_number 1 = main event), card segment, "
                "weight class, both fighters with ESPN athlete ids and records, winner, method, "
                "finishing detail, ending round and time, judges' scores and referee. Pass "
                "league => 'pfl' or 'bellator' for those promotions. Works for UFC, PFL and Bellator; "
                "for official UFC round-by-round statistics use the UFC feed functions instead."
            ),
            md=(
                "ESPN fightcenter bouts for one event. Fighter ids are ESPN athlete ids, usable with "
                "`fighter()`, `fighter_fight_history()` and `fighter_career_stats()`. An unknown event "
                "returns no rows."
            ),
            schema=BOUT_SCHEMA,
            examples=[("Results of UFC 324, main event first.", _BOUTS_SQL)],
        )
        examples = [FunctionExample(sql=_BOUTS_SQL, description="Results of UFC 324")]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """A card has roughly 10-15 bouts."""
        return TableCardinality(estimate=13, max=40)

    @classmethod
    def process(cls, params: ProcessParams[BoutsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the bouts."""
        response = api.fetch_fightcenter(params.args.league, params.args.espn_event_id)
        rows = flatten_bouts(response.payload, params.args.league) if response.payload else []
        emit(rows, params.output_schema, out, [response.ttl])


@init_single_worker
@bind_fixed_schema
class UpcomingEventsFunction(TableFunctionGenerator[None]):
    """Scheduled UFC events backing the ``upcoming_events`` table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_upcoming_events"
        description = "Scheduled UFC events this year and next (scan behind upcoming_events)"
        categories = ["mma", "events"]
        projection_pushdown = True
        tags = function_tags(
            category="events",
            title="Upcoming UFC Events (scan)",
            llm=(
                "The scan behind the upcoming_events table. Prefer the table; use events() for a past "
                "year or for PFL and Bellator."
            ),
            md="Scheduled UFC events from ESPN. Selecting `upcoming_events` is normally clearer.",
            schema=EVENT_SCHEMA,
            examples=[
                (
                    "The next three scheduled UFC events from the backing scan.",
                    "SELECT event_name, start_time, city FROM ufc.main.all_upcoming_events() "
                    "ORDER BY start_time LIMIT 3",
                )
            ],
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT event_name, start_time, city FROM ufc.main.all_upcoming_events() "
                    "ORDER BY start_time LIMIT 3"
                ),
                description="Read upcoming UFC events directly from the backing scan",
            )
        ]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """ESPN usually lists one to two months of scheduled cards."""
        return TableCardinality(estimate=6, max=60)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch this year and next year, keep scheduled events."""
        year = current_year()
        seen: dict[int, dict] = {}
        ttls: list[int] = []
        for season in (year, year + 1):
            rows, ttl = _season_rows("ufc", season)
            ttls.append(ttl)
            for row in rows:
                if row["event_state"] == "pre":
                    seen.setdefault(row["event_id"], row)
        rows = sorted(seen.values(), key=lambda row: (row["start_time"] is None, row["start_time"]))
        emit(rows, params.output_schema, out, ttls)


@init_single_worker
@bind_fixed_schema
class CurrentSeasonEventsFunction(TableFunctionGenerator[None]):
    """This year's UFC events backing the ``current_season_events`` table."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = EVENT_SCHEMA

    class Meta:
        """Function discovery metadata."""

        name = "all_current_season_events"
        description = "Every UFC event in the current calendar year (scan behind current_season_events)"
        categories = ["mma", "events"]
        projection_pushdown = True
        tags = function_tags(
            category="events",
            title="Current-Year UFC Events (scan)",
            llm="The scan behind the current_season_events table. Prefer the table.",
            md="This year's UFC calendar from ESPN. Selecting `current_season_events` is normally clearer.",
            schema=EVENT_SCHEMA,
            examples=[
                (
                    "Count this year's finished and scheduled UFC events from the backing scan.",
                    "SELECT event_state, count(*) AS events FROM ufc.main.all_current_season_events() "
                    "GROUP BY event_state ORDER BY event_state",
                )
            ],
        )
        examples = [
            FunctionExample(
                sql=(
                    "SELECT event_state, count(*) AS events FROM ufc.main.all_current_season_events() "
                    "GROUP BY event_state ORDER BY event_state"
                ),
                description="Read this year's UFC events directly from the backing scan",
            )
        ]

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """UFC runs about 40-55 events a year."""
        return TableCardinality(estimate=50, max=200)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit the current year's UFC calendar."""
        rows, ttl = _season_rows("ufc", current_year())
        emit(rows, params.output_schema, out, [ttl])


EVENT_FUNCTIONS = [EventsFunction, EventBoutsFunction, UpcomingEventsFunction, CurrentSeasonEventsFunction]
UPCOMING_SQL = _UPCOMING_SQL
SEASON_SQL = _SEASON_SQL
