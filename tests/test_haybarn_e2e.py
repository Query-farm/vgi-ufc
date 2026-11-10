"""Hermetic end-to-end coverage through Haybarn and the VGI transport."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fixture_server import serve_fixtures


def test_haybarn_attaches_and_queries_every_current_table_and_function() -> None:
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-ufc"
    sql = (
        f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'ufc' (TYPE vgi, LOCATION '{location}'); "
        "SELECT "
        "(SELECT count(*) FROM ufc.main.current_rankings) AS rankings, "
        "(SELECT count(*) FROM ufc.main.upcoming_events) AS upcoming, "
        "(SELECT count(*) FROM ufc.main.current_season_events) AS season, "
        "(SELECT count(*) FROM ufc.main.all_current_rankings()) AS rankings_scan, "
        "(SELECT count(*) FROM ufc.main.all_upcoming_events()) AS upcoming_scan, "
        "(SELECT count(*) FROM ufc.main.all_current_season_events()) AS season_scan, "
        "(SELECT count(*) FROM ufc.main.events(season := 2026)) AS events, "
        "(SELECT count(*) FROM ufc.main.event_bouts(600061268)) AS bouts, "
        "(SELECT count(*) FROM ufc.main.feed_events(1290, 1292)) AS feed, "
        "(SELECT count(*) FROM ufc.main.fight_card(1291)) AS card, "
        "(SELECT count(*) FROM ufc.main.card_fighters(1291)) AS fighters, "
        "(SELECT winner_name FROM ufc.main.fight_results(1291) WHERE fight_order = 1) AS winner, "
        "(SELECT count(*) FROM ufc.main.fight_scorecards(12000)) AS scorecards, "
        "(SELECT sum(sig_strikes_landed) FROM ufc.main.fight_stats(12000)) AS sig_landed, "
        "(SELECT count(*) FROM ufc.main.fight_round_stats(12000)) AS rounds, "
        "(SELECT record FROM ufc.main.fighter(3022677)) AS record, "
        "(SELECT count(*) FROM ufc.main.fighter_fight_history(3022677)) AS history, "
        "(SELECT count(*) FROM ufc.main.fighter_career_stats(3022677)) AS career;"
    )
    with serve_fixtures() as overrides:
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-csv", "-c", sql],
            cwd=project,
            env={**os.environ, **overrides, "AI_AGENT": ""},
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    assert result.returncode == 0, result.stderr
    lines = [
        line for line in result.stdout.splitlines() if line.startswith("rankings,") or line[:1].isdigit()
    ]
    header, values = lines[0].split(","), lines[1].split(",")
    row = dict(zip(header, values, strict=True))
    assert int(row["rankings"]) == int(row["rankings_scan"]) > 30
    assert int(row["upcoming"]) == int(row["upcoming_scan"]) > 0
    assert int(row["season"]) == int(row["season_scan"]) > int(row["upcoming"])
    assert int(row["events"]) == int(row["season"])
    assert row["bouts"] == "4"
    assert row["feed"] == "1"
    assert (row["card"], row["fighters"]) == ("4", "8")
    assert row["winner"] == "Gabriel Bonfim"
    assert (row["scorecards"], row["sig_landed"], row["rounds"]) == ("9", "146", "6")
    assert row["record"] == "22-7-0"
    assert (row["history"], row["career"]) == ("5", "5")
