"""Parsing tests for the official ufc.com rankings page."""

from __future__ import annotations

import pytest
from fixture_server import fixture_text

from vgi_ufc.convert import batch_from_rows
from vgi_ufc.rankings import RANKINGS_SCHEMA, parse_rankings

HTML = fixture_text("ufc_rankings.html")


def test_divisions_champions_and_contenders() -> None:
    rows = parse_rankings(HTML)
    divisions = {row["division"] for row in rows}
    assert divisions == {"Men's Pound-for-Pound", "Flyweight", "Women's Strawweight"}

    p4p = [row for row in rows if row["pound_for_pound"]]
    assert [row["rank"] for row in p4p] == list(range(1, 16))
    assert not any(row["is_champion"] for row in p4p)
    assert p4p[0]["fighter_name"] == "Islam Makhachev"

    flyweight = [row for row in rows if row["division"] == "Flyweight"]
    assert flyweight[0] == {
        "division": "Flyweight",
        "division_order": 2,
        "gender": "men",
        "pound_for_pound": False,
        "rank": 0,
        "is_champion": True,
        "is_interim_champion": False,
        "fighter_name": "Joshua Van",
        "fighter_slug": "joshua-van",
        "ufc_athlete_url": "https://www.ufc.com/athlete/joshua-van",
        "rank_change": None,
        "newly_ranked": False,
    }
    ranks = [row["rank"] for row in flyweight]
    # ufc.com publishes ties: two fighters share 12th and the next rank is 14th.
    assert ranks[:12] == list(range(12)) and ranks[12:] == [12, 12, 14, 15]

    women = [row for row in rows if row["division"] == "Women's Strawweight"]
    assert women[0]["gender"] == "women" and women[0]["is_champion"]


def test_rank_movement() -> None:
    rows = {(row["division"], row["fighter_slug"]): row for row in parse_rankings(HTML)}
    assert rows[("Men's Pound-for-Pound", "ciryl-gane")]["rank_change"] == -1
    assert rows[("Flyweight", "su-mudaerji")]["rank_change"] == 1
    newly = rows[("Flyweight", "charles-johnson")]
    assert newly["newly_ranked"] is True and newly["rank_change"] is None
    assert rows[("Flyweight", "manel-kape")]["rank_change"] == 0


def test_rows_fit_schema_and_keys_are_unique() -> None:
    rows = parse_rankings(HTML)
    batch = batch_from_rows(rows, RANKINGS_SCHEMA)
    assert batch.num_rows == len(rows)
    assert len({(row["division"], row["fighter_slug"]) for row in rows}) == len(rows)


def test_interim_title_is_flagged() -> None:
    html = HTML.replace('<span class="text">Champion</span>', '<span class="text">Interim Champion</span>', 1)
    champion = next(row for row in parse_rankings(html) if row["is_champion"])
    assert champion["is_interim_champion"] is True


def test_structure_change_fails_loudly() -> None:
    with pytest.raises(ValueError, match="no longer contains"):
        parse_rankings("<html><body><p>Rankings moved</p></body></html>")
