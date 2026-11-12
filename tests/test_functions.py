"""Run every table function's process() against the local fixture server."""

from __future__ import annotations

from types import SimpleNamespace

import pyarrow as pa
import pytest
from fixture_server import FixtureHandler

from vgi_ufc import event_functions as events
from vgi_ufc import fight_functions as fights
from vgi_ufc import fighter_functions as fighters
from vgi_ufc import ranking_functions as rankings
from vgi_ufc.common import cache_control


class _Out:
    def __init__(self) -> None:
        self.batches: list[pa.RecordBatch] = []
        self.cache_controls: list[object] = []
        self.finished = False

    def emit(self, batch: pa.RecordBatch, *, cache_control: object = None) -> None:
        self.batches.append(batch)
        self.cache_controls.append(cache_control)

    def finish(self) -> None:
        self.finished = True


def _run(function, args: object = None) -> pa.Table:
    out = _Out()
    function.process(SimpleNamespace(args=args, output_schema=function.FIXED_SCHEMA), None, out)
    assert out.finished
    assert out.cache_controls[0] is not None
    return pa.Table.from_batches(out.batches, schema=function.FIXED_SCHEMA)


@pytest.mark.usefixtures("fixture_env")
def test_current_tables() -> None:
    ranked = _run(rankings.CurrentRankingsFunction)
    assert ranked.num_rows > 30
    upcoming = _run(events.UpcomingEventsFunction).to_pylist()
    assert upcoming and all(row["event_state"] == "pre" for row in upcoming)
    # Next year's scoreboard is the same fixture; scheduled events are de-duplicated.
    assert len({row["event_id"] for row in upcoming}) == len(upcoming)
    season = _run(events.CurrentSeasonEventsFunction)
    assert season.num_rows > len(upcoming)


@pytest.mark.usefixtures("fixture_env")
def test_events_and_bouts() -> None:
    table = _run(events.EventsFunction, events.EventsArgs(season=2026, league="ufc"))
    assert 600057024 in table.column("event_id").to_pylist()
    assert _run(events.EventsFunction, events.EventsArgs(season=None, league="pfl")).num_rows == 0
    assert any("dates=" in path or path.endswith("/scoreboard") for path, _ in FixtureHandler.requests)

    bouts = _run(events.EventBoutsFunction, events.BoutsArgs(espn_event_id=600061268, league="ufc"))
    assert bouts.column("winner_name").to_pylist()[0] == "Johnny Walker"
    missing = _run(events.EventBoutsFunction, events.BoutsArgs(espn_event_id=1, league="ufc"))
    assert missing.num_rows == 0


@pytest.mark.usefixtures("fixture_env")
def test_feed_functions() -> None:
    scan = _run(fights.FeedEventsFunction, fights.ScanArgs(first_id=1289, last_id=1292))
    assert scan.column("event_id").to_pylist() == [1291]

    for function, expected in [
        (fights.FightCardFunction, 4),
        (fights.CardFightersFunction, 8),
        (fights.FightResultsFunction, 4),
    ]:
        assert _run(function, fights.EventArgs(event_id=1291)).num_rows == expected
    assert _run(fights.FightResultsFunction, fights.EventArgs(event_id=9999)).num_rows == 0

    assert _run(fights.FightStatsFunction, fights.FightArgs(fight_id=12000)).num_rows == 2
    assert _run(fights.FightRoundStatsFunction, fights.FightArgs(fight_id=12000)).num_rows == 6
    assert _run(fights.FightScorecardsFunction, fights.FightArgs(fight_id=12000)).num_rows == 9
    assert _run(fights.FightStatsFunction, fights.FightArgs(fight_id=1)).num_rows == 0


def test_feed_scan_bounds() -> None:
    with pytest.raises(ValueError, match="greater than or equal"):
        fights._scan(10, 5)
    with pytest.raises(ValueError, match="at most"):
        fights._scan(1, fights.MAX_SCAN_SPAN + 1)


@pytest.mark.usefixtures("fixture_env")
def test_fighter_functions() -> None:
    args = fighters.FighterArgs(fighter_id=3022677)
    assert _run(fighters.FighterFunction, args).column("fighter_name").to_pylist() == ["Conor McGregor"]
    assert _run(fighters.FighterFightHistoryFunction, args).num_rows == 5
    assert _run(fighters.FighterCareerStatsFunction, args).num_rows == 5
    unknown = fighters.FighterArgs(fighter_id=42)
    assert _run(fighters.FighterFunction, unknown).num_rows == 0
    assert _run(fighters.FighterCareerStatsFunction, unknown).num_rows == 0


def test_every_request_carries_the_honest_user_agent(fixture_env: dict[str, str]) -> None:
    _run(rankings.CurrentRankingsFunction)
    _run(fights.FightCardFunction, fights.EventArgs(event_id=1291))
    agents = {agent for _, agent in FixtureHandler.requests}
    assert agents == {"vgi-ufc/0.2.0 (+https://github.com/Query-farm/vgi-ufc)"}


def test_cache_control_uses_shortest_lifetime() -> None:
    assert cache_control([]) is None
    assert cache_control([0]) is None
    policy = cache_control([600, 60])
    assert policy.ttl == 60
    assert policy.stale_if_error == 300
