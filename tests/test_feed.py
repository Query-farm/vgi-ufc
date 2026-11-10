"""Parsing tests for the UFC live-data feed, from recorded real responses."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest
from fixture_server import fixture_json

from vgi_ufc import feed
from vgi_ufc.convert import batch_from_rows
from vgi_ufc.meta import comment_of

EVENT = fixture_json("ufc_event_1291.json")
UPCOMING = fixture_json("ufc_event_1350.json")
FIGHT = fixture_json("ufc_fight_12000.json")


def test_event_summary() -> None:
    [row] = feed.flatten_feed_event(EVENT)
    assert row["event_id"] == 1291
    assert row["event_name"] == "UFC Fight Night: Bonfim vs. Brown"
    assert row["start_time"] == datetime(2025, 11, 8, 21, 0, tzinfo=UTC)
    assert row["status"] == "Final"
    assert row["venue"] == "Meta Apex"
    assert row["main_event"] == "Gabriel Bonfim vs. Randy Brown"
    assert row["fight_count"] == 4
    assert feed.flatten_feed_event({"LiveEventDetail": {}}) == []


def test_fight_card_has_both_corners() -> None:
    rows = feed.flatten_fight_card(EVENT)
    assert [row["fight_order"] for row in rows] == sorted(row["fight_order"] for row in rows)
    main = rows[0]
    assert main["fight_id"] == 12447
    assert main["red_fighter_name"] == "Gabriel Bonfim"
    assert main["blue_fighter_name"] == "Randy Brown"
    assert main["red_record"] == "20-1-0"
    assert main["scheduled_rounds"] == 5
    assert main["referee_name"] == "Mark Smith"
    assert main["weight_class_abbreviation"] == "WW"


def test_upcoming_card_has_no_results() -> None:
    rows = feed.flatten_fight_results(UPCOMING)
    assert rows
    assert all(row["status"] == "Upcoming" for row in rows)
    assert all(row["winner_name"] is None and row["outcome"] is None for row in rows)


def test_results_ko_submission_and_decision() -> None:
    rows = {row["fight_id"]: row for row in feed.flatten_fight_results(EVENT)}
    ko = rows[12447]
    assert ko["outcome"] == "win"
    assert (ko["winner_name"], ko["loser_name"]) == ("Gabriel Bonfim", "Randy Brown")
    assert (ko["method"], ko["ending_round"], ko["ending_time"]) == ("KO/TKO", 2, "1:40")
    assert ko["ending_time_seconds"] == 100
    assert ko["fight_duration_seconds"] == 400
    assert (ko["ending_strike"], ko["ending_target"], ko["ending_position"]) == ("Knee", "Head", "In Clinch")
    assert ko["performance_bonus_names"] == "Gabriel Bonfim"
    assert ko["judges_scores"] is None

    decision = rows[12507]
    assert decision["method"] == "Decision - Unanimous"
    assert decision["winner_name"] == "Jamall Emmers"
    # Winner-first, one entry per judge.
    assert decision["judges_scores"] == "29-27, 30-27, 30-27"
    assert decision["fight_duration_seconds"] == 900

    assert rows[12502]["method"] == "Submission"


def test_draw_and_no_contest_outcomes() -> None:
    fight = {
        "FightId": 1,
        "FightOrder": 1,
        "Fighters": [
            {
                "FighterId": 10,
                "Corner": "Red",
                "Name": {"FirstName": "A", "LastName": "One"},
                "Outcome": {"Outcome": "Draw"},
            },
            {
                "FighterId": 20,
                "Corner": "Blue",
                "Name": {"FirstName": "B", "LastName": "Two"},
                "Outcome": {"Outcome": "Draw"},
            },
        ],
        "Result": {
            "Method": "Decision - Split",
            "EndingRound": 3,
            "EndingTime": "5:00",
            "FightScores": [{"Fighters": [{"FighterId": 10, "Score": 29}, {"FighterId": 20, "Score": 28}]}],
        },
    }
    [row] = feed.flatten_fight_results({"LiveEventDetail": {"EventId": 9, "FightCard": [fight]}})
    assert row["outcome"] == "Draw"
    assert row["winner_fighter_id"] is None
    assert row["judges_scores"] == "29-28"


def test_card_fighters_bio() -> None:
    rows = feed.flatten_card_fighters(EVENT)
    assert len(rows) == 8
    bonfim = rows[0]
    assert bonfim["fighter_name"] == "Gabriel Bonfim"
    assert bonfim["nickname"] == "Marretinha"
    assert bonfim["outcome"] == "Win"
    assert bonfim["date_of_birth"] == date(1997, 8, 20)
    assert bonfim["height_in"] == Decimal("73.0")
    assert bonfim["reach_in"] == Decimal("72.5")
    assert bonfim["weigh_in_lbs"] == Decimal("170.5")
    assert bonfim["ufc_athlete_url"] == "https://www.ufc.com/athlete/Gabriel-Bonfim"


def test_scorecards_per_judge_round() -> None:
    rows = feed.flatten_scorecards(FIGHT)
    assert len(rows) == 9
    totals: dict[str, tuple[int, int]] = {}
    for row in rows:
        red, blue = totals.get(row["judge_name"], (0, 0))
        totals[row["judge_name"]] = (red + row["red_score"], blue + row["blue_score"])
    assert sorted(totals.values()) == [(29, 27), (29, 28), (29, 28)]
    assert rows[0]["red_fighter_name"] == "Navajo Stirling"
    assert feed.flatten_scorecards({"LiveFightDetail": {}}) == []


def test_fight_stats_totals() -> None:
    rows = {row["corner"]: row for row in feed.flatten_fight_stats(FIGHT)}
    red = rows["Red"]
    assert red["fighter_name"] == "Navajo Stirling"
    assert red["event_id"] == 1252
    assert red["outcome"] == "Win"
    assert (red["sig_strikes_landed"], red["sig_strikes_attempted"]) == (110, 225)
    assert red["sig_strike_accuracy_pct"] == Decimal("48.89")
    assert red["knockdowns"] == 1
    assert red["takedowns_landed"] == 3
    assert red["control_seconds"] == 181
    assert feed.flatten_fight_stats({"LiveFightDetail": {}}) == []


def test_round_stats_sum_to_fight_totals() -> None:
    rounds = feed.flatten_round_stats(FIGHT)
    totals = {row["fighter_id"]: row for row in feed.flatten_fight_stats(FIGHT)}
    assert {row["round_number"] for row in rounds} == {1, 2, 3}
    assert rounds[0]["corner"] == "Red"
    assert rounds[0]["sig_strikes_landed"] == 31
    assert rounds[0]["takedown_accuracy_pct"] is None
    for fighter_id, total in totals.items():
        landed = sum(r["sig_strikes_landed"] for r in rounds if r["fighter_id"] == fighter_id)
        assert landed == total["sig_strikes_landed"]
    assert feed.flatten_round_stats({"LiveFightDetail": {}}) == []


@pytest.mark.parametrize(
    ("schema", "rows"),
    [
        (feed.FEED_EVENT_SCHEMA, feed.flatten_feed_event(EVENT)),
        (feed.FIGHT_CARD_SCHEMA, feed.flatten_fight_card(EVENT)),
        (feed.CARD_FIGHTER_SCHEMA, feed.flatten_card_fighters(EVENT)),
        (feed.FIGHT_RESULT_SCHEMA, feed.flatten_fight_results(EVENT)),
        (feed.SCORECARD_SCHEMA, feed.flatten_scorecards(FIGHT)),
        (feed.FIGHT_STATS_SCHEMA, feed.flatten_fight_stats(FIGHT)),
        (feed.ROUND_STATS_SCHEMA, feed.flatten_round_stats(FIGHT)),
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
