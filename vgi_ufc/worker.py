"""VGI worker exposing UFC cards, results, fight statistics, fighters, and rankings as SQL."""

from __future__ import annotations

import json
import os
import sys

from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_ufc.espn import EVENT_SCHEMA
from vgi_ufc.event_functions import (
    EVENT_FUNCTIONS,
    SEASON_SQL,
    UPCOMING_SQL,
    CurrentSeasonEventsFunction,
    UpcomingEventsFunction,
)
from vgi_ufc.fight_functions import (
    FIGHT_FUNCTIONS,
    JUDGES_VS_STRIKES_DESCRIPTION,
    JUDGES_VS_STRIKES_SQL,
    RANKED_ON_CARD_DESCRIPTION,
    RANKED_ON_CARD_SQL,
    REACH_EDGE_DESCRIPTION,
    REACH_EDGE_SQL,
)
from vgi_ufc.fighter_functions import FIGHTER_FUNCTIONS
from vgi_ufc.meta import column_comments
from vgi_ufc.ranking_functions import RANKING_FUNCTIONS, CurrentRankingsFunction
from vgi_ufc.rankings import RANKINGS_SCHEMA

SOURCE_URL = "https://github.com/Query-farm/vgi-ufc"

_RANKINGS_SQL = (
    "SELECT division, rank, fighter_name, rank_change FROM ufc.main.current_rankings "
    "WHERE division = 'Lightweight' ORDER BY rank"
)
_CHAMPIONS_SQL = (
    "SELECT division, fighter_name, is_interim_champion FROM ufc.main.current_rankings "
    "WHERE is_champion ORDER BY division_order"
)

_RANKINGS_EXAMPLES = [
    {"description": "The current lightweight top 15.", "sql": _RANKINGS_SQL},
    {"description": "Every current UFC champion.", "sql": _CHAMPIONS_SQL},
]
_SCHEMA_EXAMPLES = json.dumps(
    [
        *_RANKINGS_EXAMPLES,
        {"description": JUDGES_VS_STRIKES_DESCRIPTION, "sql": JUDGES_VS_STRIKES_SQL},
        {"description": REACH_EDGE_DESCRIPTION, "sql": REACH_EDGE_SQL},
        {"description": RANKED_ON_CARD_DESCRIPTION, "sql": RANKED_ON_CARD_SQL},
    ]
)

_RANKINGS_TAGS = {
    "provider": "ufc",
    "vgi.category": "rankings",
    "vgi.title": "Current UFC Rankings",
    "vgi.keywords": json.dumps(["rankings", "champions", "pound-for-pound", "contenders", "divisions"]),
    "vgi.doc_llm": (
        "The official current UFC rankings from ufc.com, one row per fighter per list. Each weight "
        "class has its champion as rank 0 (is_champion = true) and contenders ranked 1-15; the men's "
        "and women's pound-for-pound lists have ranks 1-15 only (pound_for_pound = true). rank_change "
        "is places gained (+) or lost (-) since the last update, and newly_ranked marks fighters who "
        "were unranked. Fighters are identified by ufc.com slug and name, not by numeric id."
    ),
    "vgi.doc_md": (
        "Official UFC rankings scraped on demand from ufc.com/rankings and cached for up to an hour. "
        "Champions are rank 0. ESPN's MMA rankings are stale and are intentionally not used."
    ),
    "vgi.example_queries": json.dumps(_RANKINGS_EXAMPLES),
}

_UPCOMING_TAGS = {
    "provider": "ufc",
    "vgi.category": "events",
    "vgi.title": "Upcoming UFC Events",
    "vgi.keywords": json.dumps(["schedule", "upcoming", "next event", "fight night", "pay-per-view"]),
    "vgi.doc_llm": (
        "Scheduled (not yet started) UFC events from ESPN for this year and next, one row per event "
        "with ESPN event_id, name, start time, venue, city and bout count. Pass event_id to "
        "event_bouts() for the announced matchups."
    ),
    "vgi.doc_md": "UFC events ESPN lists as scheduled, soonest first.",
    "vgi.example_queries": json.dumps(
        [
            {"description": "The upcoming UFC schedule.", "sql": UPCOMING_SQL},
        ]
    ),
}

_SEASON_TAGS = {
    "provider": "ufc",
    "vgi.category": "events",
    "vgi.title": "This Year's UFC Events",
    "vgi.keywords": json.dumps(["calendar", "season", "events", "results", "this year"]),
    "vgi.doc_llm": (
        "Every UFC event ESPN lists for the current calendar year, finished and scheduled, one row per "
        "event (event_state pre, in, or post). Use events(season := YYYY) for another year and "
        "event_bouts(event_id) for results."
    ),
    "vgi.doc_md": "The current year's UFC calendar from ESPN.",
    "vgi.example_queries": json.dumps(
        [
            {"description": "This year's UFC events in date order.", "sql": SEASON_SQL},
        ]
    ),
}

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "rankings_have_champions",
            "description": "The official rankings list a champion in every weight class.",
            "sql": (
                "SELECT count(*) >= 8 AS has_champions FROM ufc.main.current_rankings "
                "WHERE is_champion AND NOT pound_for_pound"
            ),
            "expected_result": [{"has_champions": True}],
        },
        {
            "name": "current_season_has_events",
            "description": "ESPN lists UFC events for the current year.",
            "sql": "SELECT count(*) > 0 AS populated FROM ufc.main.current_season_events",
            "expected_result": [{"populated": True}],
        },
        {
            "name": "feed_event_1291_main_event",
            "description": "The UFC feed records Gabriel Bonfim's KO/TKO win in the 2025-11-08 main event.",
            "sql": (
                "SELECT winner_name, method, ending_round FROM ufc.main.fight_results(1291) "
                "WHERE fight_order = 1"
            ),
            "expected_result": [{"winner_name": "Gabriel Bonfim", "method": "KO/TKO", "ending_round": 2}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "current_champions",
            "prompt": "Who are the current UFC champions in every men's and women's weight class?",
        },
        {
            "name": "next_ufc_event",
            "prompt": "When and where is the next scheduled UFC event, and what is it called?",
        },
        {
            "name": "events_this_year",
            "prompt": (
                "How many UFC events have already taken place this calendar year, and how many PFL "
                "events did ESPN list for 2026?"
            ),
        },
        {
            "name": "ufc_324_results",
            "prompt": "Using ESPN event id 600057024 (UFC 324), who won the main event and by what method?",
        },
        {
            "name": "feed_event_lookup",
            "prompt": (
                "Find the UFC live-data feed event id for UFC 324 (feed ids between 1290 and 1300) and "
                "name the two fighters in its main event."
            ),
        },
        {
            "name": "card_results_1291",
            "prompt": (
                "UFC's official feed id 1291 is the 2025-11-08 Fight Night. List every fight's winner, "
                "method, and ending round in card order."
            ),
        },
        {
            "name": "longest_reach_1291",
            "prompt": "Which fighter on UFC feed event 1291 had the longest reach, and how long was it?",
        },
        {
            "name": "fight_12000_breakdown",
            "prompt": (
                "For UFC fight id 12000, give each fighter's total significant strikes, their landed "
                "significant strikes in each round, and each judge's total score."
            ),
        },
        {
            "name": "mcgregor_profile",
            "prompt": (
                "What is Conor McGregor's professional record, how many wins came by KO/TKO, and how "
                "many knockdowns has he scored across ESPN-tracked fights? His ESPN id is 3022677."
            ),
        },
        {
            "name": "mcgregor_recent_fights",
            "prompt": "List the five most recent fights of Conor McGregor (ESPN id 3022677) with results.",
        },
        {
            "name": "judges_vs_striking_12000",
            "prompt": (
                "In UFC fight id 12000, which judges scored a round for the fighter who landed fewer "
                "significant strikes in that round? Give each judge, the round, and both fighters' "
                "landed significant strikes for it."
            ),
        },
        {
            "name": "main_event_strikes_1291",
            "prompt": (
                "For the main event of UFC feed event 1291, how did the fight end (method, round and "
                "time), and how many significant strikes did each fighter land and attempt?"
            ),
        },
    ]
)


def _key_constraints(table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            ["main"],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            ["main"],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


_CATEGORIES = [
    {
        "name": "rankings",
        "title": "Rankings",
        "description": "Official UFC divisional and pound-for-pound rankings, champions as rank 0.",
        "keywords": ["rankings", "champions", "pound-for-pound"],
    },
    {
        "name": "events",
        "title": "Events",
        "description": "Event calendars and bout results for UFC, PFL, and Bellator from ESPN.",
        "keywords": ["schedule", "calendar", "events", "results"],
    },
    {
        "name": "fight-cards",
        "title": "UFC Fight Cards",
        "description": "Official UFC cards and fighter details from UFC's live-data feed.",
        "keywords": ["fight card", "matchups", "corners", "weigh-in"],
    },
    {
        "name": "results",
        "title": "Results",
        "description": "Official UFC results, finishing details, and judges' scorecards.",
        "keywords": ["results", "method", "decision", "scorecards", "bonuses"],
    },
    {
        "name": "fight-stats",
        "title": "Fight Statistics",
        "description": "Official UFC whole-fight and per-round striking and grappling statistics.",
        "keywords": ["significant strikes", "takedowns", "control time", "knockdowns"],
    },
    {
        "name": "fighters",
        "title": "Fighters",
        "description": "ESPN fighter profiles, fight histories, and per-fight career statistics.",
        "keywords": ["fighter", "record", "career", "history"],
    },
]

UFC_CATALOG = Catalog(
    name="ufc",
    default_schema="main",
    source_url=SOURCE_URL,
    comment=(
        "Read-only UFC rankings, events, fight cards, results, and fight statistics from UFC's official "
        "feed, ufc.com, and ESPN"
    ),
    tags={
        "provider": "ufc",
        "domain": "sports",
        "vgi.title": "UFC Fight Data",
        "vgi.subtitle": "UFC rankings, cards, results, and round-by-round fight stats as SQL tables.",
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. Not affiliated with UFC, TKO Group, ESPN, or Disney. "
            "UFC data (c) Zuffa, LLC; ESPN data (c) ESPN Enterprises, Inc.; use is subject to each "
            "source's terms."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-ufc/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-ufc/blob/main/README.md",
        "vgi.keywords": json.dumps(["UFC", "MMA", "mixed martial arts", "fight stats", "rankings", "PFL"]),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only mixed martial arts data. current_rankings holds the official ufc.com rankings "
            "(champions as rank 0); upcoming_events and current_season_events list UFC events from "
            "ESPN. Two id systems exist. ESPN ids (event_id from events/upcoming_events, athlete ids "
            "from event_bouts) work with event_bouts, fighter, fighter_fight_history and "
            "fighter_career_stats, and cover PFL and Bellator too. UFC's official live-data feed uses "
            "its own sequential integers: find an event id with feed_events(first_id, last_id) (1291 = "
            "2025-11-08, 1343 = 2026-11-07), then use fight_card, card_fighters and fight_results; "
            "their fight_id values feed fight_stats, fight_round_stats and fight_scorecards."
        ),
        "vgi.doc_md": (
            "# UFC fight data\n\n"
            "Query official UFC rankings, event calendars, fight cards, results, judges' scorecards, "
            "and round-by-round fight statistics directly from SQL.\n\n"
            "## Sources and ids\n\n"
            "* **UFC live-data feed** (official): cards, results, per-round statistics. Event and fight "
            "ids are sequential integers; discover them with `feed_events()`.\n"
            "* **ufc.com/rankings** (official): current rankings.\n"
            "* **ESPN** (unofficial, undocumented): calendars for UFC, PFL and Bellator, bout results, "
            "and fighter profiles, histories and per-fight statistics. ESPN ids differ from UFC ids.\n\n"
            "All data is fetched on demand, cached briefly in process, and never rehosted. This worker "
            "is not affiliated with UFC, TKO Group, ESPN, or Disney."
        ),
    },
    schemas=[
        Schema(
            path=["main"],
            comment="UFC rankings, events, cards, results, fight statistics, and fighters",
            tags={
                "provider": "ufc",
                "domain": "sports",
                "vgi.title": "UFC",
                "vgi.keywords": json.dumps(
                    ["UFC", "MMA", "rankings", "fight card", "results", "significant strikes", "fighters"]
                ),
                "vgi.categories": json.dumps(_CATEGORIES),
                "vgi.doc_llm": (
                    "Mixed martial arts analysis from three sources. Official ufc.com rankings and "
                    "ESPN calendars answer who holds which belt and what is scheduled. ESPN ids link "
                    "events, bouts and fighter careers across UFC, PFL and Bellator. UFC's own feed "
                    "carries the authoritative card, result, judging and round-by-round striking and "
                    "grappling detail, keyed by sequential event and fight ids that are discovered by "
                    "scanning an id range. ESPN and UFC feed ids are different systems and never join."
                ),
                "vgi.doc_md": (
                    "## UFC analytical data\n\n"
                    "Rows are explicitly ranking-, event-, bout-, fighter-, fight-fighter- or "
                    "fight-fighter-round-grain. Current tables need no arguments; functions take a "
                    "season, an ESPN id, or a UFC feed id.\n\n"
                    "ESPN identifiers (events and athletes) and UFC live-data feed identifiers (events, "
                    "fights and fighters) are separate numbering systems. Match across them by event "
                    "date and fighter name, not by id.\n\n"
                    "Use the ESPN side for calendars, other promotions and career histories; use the "
                    "UFC feed side for official per-fight and per-round statistics and scorecards."
                ),
                "vgi.example_queries": _SCHEMA_EXAMPLES,
            },
            functions=[*RANKING_FUNCTIONS, *EVENT_FUNCTIONS, *FIGHT_FUNCTIONS, *FIGHTER_FUNCTIONS],
            tables=[
                Table(
                    name="current_rankings",
                    function=CurrentRankingsFunction,
                    comment="Official current UFC rankings, one row per fighter per division list",
                    tags=_RANKINGS_TAGS,
                    column_comments=column_comments(RANKINGS_SCHEMA),
                    constraints=_key_constraints("current_rankings", ("division", "fighter_slug")),
                    cardinality_estimate=206,
                ),
                Table(
                    name="upcoming_events",
                    function=UpcomingEventsFunction,
                    comment="Scheduled UFC events for this year and next, one row per event",
                    tags=_UPCOMING_TAGS,
                    column_comments=column_comments(EVENT_SCHEMA),
                    constraints=_key_constraints("upcoming_events", ("event_id",)),
                    cardinality_estimate=6,
                ),
                Table(
                    name="current_season_events",
                    function=CurrentSeasonEventsFunction,
                    comment="Every UFC event in the current calendar year, one row per event",
                    tags=_SEASON_TAGS,
                    column_comments=column_comments(EVENT_SCHEMA),
                    constraints=_key_constraints("current_season_events", ("event_id",)),
                    cardinality_estimate=50,
                ),
            ],
        )
    ],
)


class UfcWorker(Worker):
    """Worker process hosting the read-only UFC catalog."""

    catalog = UFC_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    UfcWorker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    UfcWorker.main()
