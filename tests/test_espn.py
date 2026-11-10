"""Parsing tests for ESPN MMA payloads, from recorded real responses."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pyarrow as pa
import pytest
from fixture_server import fixture_json

from vgi_ufc import espn
from vgi_ufc.convert import batch_from_rows
from vgi_ufc.meta import comment_of

SCOREBOARD = fixture_json("espn_scoreboard_ufc_2026.json")
FIGHTCENTER = fixture_json("espn_fightcenter_600061268.json")
ATHLETE = fixture_json("espn_athlete_3022677.json")
STATS = fixture_json("espn_athlete_3022677_stats.json")


def test_events_from_scoreboard() -> None:
    rows = espn.flatten_events(SCOREBOARD, "ufc")
    by_id = {row["event_id"]: row for row in rows}
    ufc324 = by_id[600057024]
    assert ufc324["event_name"] == "UFC 324: Gaethje vs. Pimblett"
    assert ufc324["short_name"] == "UFC 324"
    assert ufc324["city"] == "Las Vegas"
    assert ufc324["event_state"] == "post"
    assert ufc324["completed"] is True
    assert ufc324["season"] == 2026
    assert ufc324["league"] == "ufc"
    scheduled = [row for row in rows if row["event_state"] == "pre"]
    assert scheduled and all(row["completed"] is False for row in scheduled)
    assert [row["start_time"] for row in rows] == sorted(row["start_time"] for row in rows)


def test_bouts_from_fightcenter() -> None:
    rows = espn.flatten_bouts(FIGHTCENTER, "ufc")
    assert [row["match_number"] for row in rows] == sorted(row["match_number"] for row in rows)
    main = rows[0]
    assert main["match_number"] == 1
    assert main["event_name"] == "UFC Fight Night: Cortes Acosta vs. Walker"
    assert main["winner_name"] == "Johnny Walker"
    assert (main["method"], main["method_detail"]) == ("KO/TKO", "Punch")
    assert (main["ending_round"], main["ending_time"]) == (3, "2:27")
    assert main["fight_duration_seconds"] == 747
    assert main["referee_name"] == "Jason Herzog"
    assert main["card_segment"] == "main"
    decision = next(row for row in rows if row["judges_scores"])
    assert decision["method"] == "Decision - Unanimous"
    # ESPN orders each judge's card fighter1-fighter2.
    assert decision["judges_scores"] == "30-27 | 29-28 | 30-27"


def test_unfinished_bout_has_no_result() -> None:
    payload = {
        "event": {"id": "1", "name": "Future"},
        "cards": {
            "main": {
                "cardSegment": "main",
                "competitions": [
                    {
                        "id": "9",
                        "matchNumber": 1,
                        "note": "Lightweight - Main Event - Title Fight",
                        "status": {"period": 0, "displayClock": "0:00", "type": {"completed": False}},
                        "competitors": [{"id": "1", "order": 1}, {"id": "2", "order": 2}],
                    }
                ],
            }
        },
    }
    [row] = espn.flatten_bouts(payload, "pfl")
    assert row["title_fight"] is True
    assert row["winner_id"] is None and row["method"] is None and row["ending_round"] is None


def test_fighter_profile() -> None:
    [row] = espn.flatten_fighter(ATHLETE)
    assert row["fighter_name"] == "Conor McGregor"
    assert row["nickname"] == "The Notorious"
    assert row["date_of_birth"] == date(1988, 7, 14)
    assert row["height_in"] == Decimal("69.0")
    assert row["reach_in"] == Decimal("74.0")
    assert row["weight_lbs"] == Decimal("170.0")
    assert row["stance"] == "Southpaw"
    assert (row["record"], row["wins"], row["losses"], row["draws"]) == ("22-7-0", 22, 7, 0)
    assert (row["ko_tko_wins"], row["ko_tko_losses"]) == (19, 3)
    assert (row["submission_wins"], row["submission_losses"]) == (1, 4)
    assert espn.flatten_fighter(None) == []


def test_fight_history_most_recent_first() -> None:
    rows = espn.flatten_fight_history(ATHLETE)
    assert [row["fight_number"] for row in rows] == [1, 2, 3, 4, 5]
    latest = rows[0]
    assert latest["opponent_name"] == "Max Holloway"
    assert latest["result"] == "L"
    assert latest["league"] == "UFC"
    assert latest["event_id"] == 600059148 and latest["bout_id"] == 401867788
    assert latest["ending_round"] == 1 and latest["ending_time"] == "1:09"
    assert espn.flatten_fight_history({}) == []


def test_career_stats_join_profile() -> None:
    rows = espn.flatten_career_stats(STATS, ATHLETE, 3022677)
    assert len(rows) == 5
    by_event = {row["event_id"]: row for row in rows}
    poirier = by_event[600005500]
    assert poirier["opponent_name"] == "Dustin Poirier"
    assert (poirier["sig_strikes_landed"], poirier["sig_strikes_attempted"]) == (27, 38)
    assert (poirier["sig_distance_leg_landed"], poirier["sig_distance_leg_attempted"]) == (8, 8)
    assert poirier["total_strike_accuracy_pct"] == Decimal("79.63")
    assert poirier["head_target_pct"] == Decimal("62.00")
    # ESPN's "target breakdown" is per-target accuracy: 13 of 21 head strikes landed.
    head = [
        poirier[f"sig_{p}_head_{k}"]
        for k in ("landed", "attempted")
        for p in ("distance", "clinch", "ground")
    ]
    assert round(100 * sum(head[:3]) / sum(head[3:])) == 62
    assert by_event[401186853]["knockdowns"] == 1
    # Accuracy with nothing attempted is undefined: NULL, not ESPN's 0%.
    holloway = by_event[600059148]
    assert holloway["head_target_pct"] == Decimal("0.00")
    assert holloway["sig_distance_body_attempted"] == 0
    assert holloway["body_target_pct"] is None
    assert holloway["takedowns_attempted"] == 0 and holloway["takedown_accuracy_pct"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("5' 9\"", Decimal("69.0")), ("6' 0\"", Decimal("72.0")), ("tall", None), (None, None)],
)
def test_height_inches(value, expected) -> None:
    assert espn.height_inches(value) == expected


def test_display_parsers() -> None:
    assert espn.day_month_year("14/7/1988") == date(1988, 7, 14)
    assert espn.day_month_year("31/2/2000") is None
    assert espn.day_month_year("1988-07-14") is None
    assert espn.leading_number("--") is None
    assert espn.parse_uid("s:3301~l:3321~e:600059148~c:401867788") == {
        "l": 3321,
        "e": 600059148,
        "c": 401867788,
    }
    assert espn.parse_uid(None) == {}


@pytest.mark.parametrize(
    ("schema", "rows"),
    [
        (espn.EVENT_SCHEMA, espn.flatten_events(SCOREBOARD, "ufc")),
        (espn.BOUT_SCHEMA, espn.flatten_bouts(FIGHTCENTER, "ufc")),
        (espn.FIGHTER_SCHEMA, espn.flatten_fighter(ATHLETE)),
        (espn.FIGHT_HISTORY_SCHEMA, espn.flatten_fight_history(ATHLETE)),
        (espn.CAREER_STATS_SCHEMA, espn.flatten_career_stats(STATS, ATHLETE, 3022677)),
    ],
)
def test_rows_fit_declared_schema(schema: pa.Schema, rows: list[dict]) -> None:
    batch = batch_from_rows(rows, schema)
    assert batch.num_rows == len(rows) > 0
    assert all(comment_of(value) for value in schema)
    assert len(set(schema.names)) == len(schema.names)
    for value in schema:
        if not value.nullable:
            assert batch.column(value.name).null_count == 0, value.name
