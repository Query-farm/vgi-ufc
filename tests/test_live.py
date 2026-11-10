"""Opt-in smoke tests against the real UFC feed, ESPN, and ufc.com."""

from __future__ import annotations

import pytest

from vgi_ufc import api, espn, feed
from vgi_ufc.rankings import parse_rankings

pytestmark = pytest.mark.live


def test_pinned_feed_event_1291() -> None:
    payload = api.fetch_feed_event(1291).payload
    [event] = feed.flatten_feed_event(payload)
    assert event["event_name"] == "UFC Fight Night: Bonfim vs. Brown"
    results = feed.flatten_fight_results(payload)
    assert len(results) == 12
    main = results[0]
    assert (main["winner_name"], main["method"], main["ending_round"], main["ending_time"]) == (
        "Gabriel Bonfim",
        "KO/TKO",
        2,
        "1:40",
    )


def test_pinned_fight_12000_rounds_sum_to_totals() -> None:
    payload = api.fetch_feed_fight(12000).payload
    totals = {row["fighter_id"]: row["sig_strikes_landed"] for row in feed.flatten_fight_stats(payload)}
    rounds = feed.flatten_round_stats(payload)
    assert totals == {4252: 110, 4271: 36}
    for fighter_id, landed in totals.items():
        assert sum(r["sig_strikes_landed"] for r in rounds if r["fighter_id"] == fighter_id) == landed
    assert len(feed.flatten_scorecards(payload)) == 9


def test_feed_scan_finds_ufc_324() -> None:
    names = {
        row["event_id"]: row["event_name"]
        for result in api.fetch_feed_events(range(1292, 1297))
        for row in feed.flatten_feed_event(result.payload)
    }
    assert names[1294] == "UFC 324: Gaethje vs. Pimblett"


def test_espn_calendar_and_fightcenter() -> None:
    events = espn.flatten_events(api.fetch_scoreboard("ufc", 2025).payload, "ufc")
    assert len(events) >= 40
    assert all(row["event_state"] == "post" for row in events)
    bouts = espn.flatten_bouts(api.fetch_fightcenter("ufc", 600057024).payload, "ufc")
    main = bouts[0]
    assert main["match_number"] == 1
    assert main["winner_name"] == "Justin Gaethje"
    assert main["method"] == "Decision - Unanimous"


def test_espn_pfl_calendar() -> None:
    events = espn.flatten_events(api.fetch_scoreboard("pfl", 2026).payload, "pfl")
    assert events and all(row["event_name"].startswith("PFL") for row in events)


def test_espn_fighter_profile_and_history() -> None:
    profile = api.fetch_athlete(3022677).payload
    [fighter] = espn.flatten_fighter(profile)
    assert fighter["fighter_name"] == "Conor McGregor"
    assert fighter["wins"] >= 22
    history = espn.flatten_fight_history(profile)
    assert len(history) >= 28
    assert any(row["opponent_name"] == "Khabib Nurmagomedov" and row["result"] == "L" for row in history)
    stats = espn.flatten_career_stats(api.fetch_athlete_stats(3022677).payload, profile, 3022677)
    assert len(stats) >= 20
    assert sum(row["knockdowns"] or 0 for row in stats) >= 10


def test_official_rankings() -> None:
    rows = parse_rankings(api.fetch_rankings_html().payload)
    divisions = {row["division"] for row in rows}
    assert len(divisions) >= 13
    champions = [row for row in rows if row["is_champion"]]
    assert len(champions) >= 10
    assert len({(row["division"], row["fighter_slug"]) for row in rows}) == len(rows)
