"""Arrow schemas and flattening for ESPN's undocumented MMA endpoints.

ESPN supplies the event calendar (UFC, PFL, and historical Bellator), the
fightcenter result pages, and fighter profiles, fight histories, and per-fight
career statistics. ESPN's MMA *rankings* are stale and are deliberately never
read; current rankings come from ufc.com instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

import pyarrow as pa

from vgi_ufc.convert import (
    clock_seconds,
    fight_seconds,
    landed_attempted,
    mapping,
    sequence,
    text,
    to_bool,
    to_decimal,
    to_int,
    to_timestamp,
)
from vgi_ufc.meta import field

TIMESTAMP = pa.timestamp("us", tz="UTC")
INCHES = pa.decimal128(4, 1)
PERCENT = pa.decimal128(5, 2)

#: ESPN league slugs accepted by the event functions.
LEAGUES = ("ufc", "pfl", "bellator")
#: ESPN numeric league ids (from ``s:3301~l:<id>`` uids) with a known name.
LEAGUE_NAMES = {3321: "UFC", 3323: "Bellator", 3347: "PFL"}

EVENT_SCHEMA = pa.schema(
    [
        field("league", pa.string(), "ESPN league slug: ufc, pfl, or bellator."),
        field("event_id", pa.int64(), "ESPN event identifier (use with event_bouts).", nullable=False),
        field("event_name", pa.string(), "Event name, for example 'UFC 324: Gaethje vs. Pimblett'."),
        field("short_name", pa.string(), "Short event name, for example 'UFC 324' or 'UFC Fight Night'."),
        field("start_time", TIMESTAMP, "Scheduled start of the first bout in UTC."),
        field("season", pa.int32(), "Calendar year the event belongs to."),
        field("venue", pa.string(), "Venue name."),
        field("city", pa.string(), "Venue city."),
        field("region", pa.string(), "Venue state, province, or region, when supplied."),
        field("country", pa.string(), "Venue country."),
        field("status", pa.string(), "Event status description, such as Scheduled or Final."),
        field("event_state", pa.string(), "Event state: pre (scheduled), in (live), or post (finished)."),
        field("completed", pa.bool_(), "Whether every bout on the event has finished."),
        field("bout_count", pa.int32(), "Number of bouts ESPN lists for the event."),
        field("broadcast", pa.string(), "Primary broadcast or streaming service, when listed."),
    ]
)

BOUT_SCHEMA = pa.schema(
    [
        field("league", pa.string(), "ESPN league slug: ufc, pfl, or bellator."),
        field("event_id", pa.int64(), "ESPN event identifier."),
        field("event_name", pa.string(), "Event name."),
        field("bout_id", pa.int64(), "ESPN competition identifier for the bout.", nullable=False),
        field("match_number", pa.int32(), "Running order; 1 is the main event."),
        field("card_segment", pa.string(), "Card segment slug: main, prelims1, or prelims2."),
        field("card_segment_name", pa.string(), "Card segment display name, such as Main Card or Prelims."),
        field("start_time", TIMESTAMP, "Scheduled bout start time in UTC."),
        field("weight_class", pa.string(), "Weight class."),
        field("note", pa.string(), "ESPN bout note, such as 'Lightweight - Main Event - Title Fight'."),
        field("title_fight", pa.bool_(), "Whether ESPN labels the bout a title fight."),
        field("status", pa.string(), "Bout status description, such as Scheduled or Final."),
        field("completed", pa.bool_(), "Whether the bout has finished."),
        field("fighter1_id", pa.int64(), "ESPN athlete identifier of the first-listed fighter."),
        field("fighter1_name", pa.string(), "First-listed fighter's name."),
        field(
            "fighter1_record", pa.string(), "First-listed fighter's current record (W-L-D), not at bout time."
        ),
        field("fighter2_id", pa.int64(), "ESPN athlete identifier of the second-listed fighter."),
        field("fighter2_name", pa.string(), "Second-listed fighter's name."),
        field(
            "fighter2_record",
            pa.string(),
            "Second-listed fighter's current record (W-L-D), not at bout time.",
        ),
        field(
            "winner_id",
            pa.int64(),
            "ESPN athlete identifier of the winner; null for a draw, NC, or unfought bout.",
        ),
        field("winner_name", pa.string(), "Winner's name."),
        field("method", pa.string(), "Result method, such as KO/TKO, Submission, or Decision - Unanimous."),
        field(
            "method_detail", pa.string(), "Finishing technique or detail, such as Punch or Rear Naked Choke."
        ),
        field("ending_round", pa.int32(), "Round in which the bout ended (or the current round if live)."),
        field("ending_time", pa.string(), "Clock time within the ending round, as M:SS."),
        field(
            "fight_duration_seconds", pa.int32(), "Total bout time in seconds, assuming five-minute rounds."
        ),
        field(
            "judges_scores",
            pa.string(),
            "Judges' totals for decisions, each as fighter1-fighter2 (not winner first).",
        ),
        field("referee_name", pa.string(), "Referee."),
    ]
)

FIGHTER_SCHEMA = pa.schema(
    [
        field("fighter_id", pa.int64(), "ESPN athlete identifier.", nullable=False),
        field("fighter_name", pa.string(), "Full name."),
        field("first_name", pa.string(), "First name."),
        field("last_name", pa.string(), "Last name."),
        field("nickname", pa.string(), "Nickname, when known."),
        field("gender", pa.string(), "Gender as listed by ESPN."),
        field("date_of_birth", pa.date32(), "Date of birth."),
        field("age", pa.int32(), "Age in years."),
        field("height_in", INCHES, "Height in inches."),
        field("weight_lbs", INCHES, "Listed weight in pounds."),
        field("reach_in", INCHES, "Reach in inches."),
        field("stance", pa.string(), "Stance, such as Orthodox or Southpaw."),
        field("fighting_style", pa.string(), "Primary fighting style, such as Striker or Wrestler."),
        field("weight_class", pa.string(), "Current weight class."),
        field("association", pa.string(), "Gym or team association."),
        field("citizenship", pa.string(), "Citizenship country."),
        field("active", pa.bool_(), "Whether ESPN lists the fighter as active."),
        field("record", pa.string(), "Professional record as W-L-D."),
        field("wins", pa.int32(), "Professional wins."),
        field("losses", pa.int32(), "Professional losses."),
        field("draws", pa.int32(), "Professional draws."),
        field("ko_tko_wins", pa.int32(), "Wins by KO or TKO."),
        field("ko_tko_losses", pa.int32(), "Losses by KO or TKO."),
        field("submission_wins", pa.int32(), "Wins by submission."),
        field("submission_losses", pa.int32(), "Losses by submission."),
    ]
)

FIGHT_HISTORY_SCHEMA = pa.schema(
    [
        field("fighter_id", pa.int64(), "ESPN athlete identifier.", nullable=False),
        field("fight_number", pa.int32(), "Recency rank; 1 is the most recent fight.", nullable=False),
        field("event_id", pa.int64(), "ESPN event identifier."),
        field("bout_id", pa.int64(), "ESPN competition identifier for the bout."),
        field("league_id", pa.int32(), "ESPN numeric league identifier for the promotion."),
        field("league", pa.string(), "Promotion name when known to the worker: UFC, PFL, or Bellator."),
        field("event_name", pa.string(), "Event name."),
        field("event_short_name", pa.string(), "Short event name."),
        field("event_time", TIMESTAMP, "Event date and time in UTC."),
        field("result", pa.string(), "Result for this fighter: W, L, D, or NC."),
        field("opponent_id", pa.int64(), "ESPN athlete identifier of the opponent."),
        field("opponent_name", pa.string(), "Opponent's name."),
        field(
            "method",
            pa.string(),
            "Result method as ESPN displays it, such as KO/TKO or Decision - Unanimous.",
        ),
        field("ending_round", pa.int32(), "Round in which the fight ended."),
        field("ending_time", pa.string(), "Clock time within the ending round, as M:SS, when known."),
        field("title_fight", pa.bool_(), "Whether the bout was a title fight."),
    ]
)

# (column, ESPN category, ESPN label, comment, kind)
_CAREER_STATS: list[tuple[str, str, str, str, str]] = [
    ("knockdowns", "striking", "KD", "Knockdowns scored.", "int"),
    ("total_strikes_landed", "striking", "TSL", "Total strikes landed.", "int"),
    ("total_strikes_attempted", "striking", "TSA", "Total strikes attempted.", "int"),
    ("total_strike_accuracy_pct", "striking", "TSL-TSA", "Total strike accuracy percentage.", "pct"),
    ("sig_strikes_landed", "striking", "SSL", "Significant strikes landed.", "int"),
    ("sig_strikes_attempted", "striking", "SSA", "Significant strikes attempted.", "int"),
    ("sig_distance_head", "striking", "SDHL/A", "Significant distance head strikes", "pair"),
    ("sig_distance_body", "striking", "SDBL/A", "Significant distance body strikes", "pair"),
    ("sig_distance_leg", "striking", "SDLL/A", "Significant distance leg strikes", "pair"),
    ("head_target_pct", "striking", "%HEAD", "Head significant-strike accuracy percent.", "pct"),
    ("body_target_pct", "striking", "%BODY", "Body significant-strike accuracy percent.", "pct"),
    ("leg_target_pct", "striking", "%LEG", "Leg significant-strike accuracy percent.", "pct"),
    ("sig_clinch_head_landed", "clinch", "SCHL", "Significant clinch head strikes landed.", "int"),
    ("sig_clinch_head_attempted", "clinch", "SCHA", "Significant clinch head strikes attempted.", "int"),
    ("sig_clinch_body_landed", "clinch", "SCBL", "Significant clinch body strikes landed.", "int"),
    ("sig_clinch_body_attempted", "clinch", "SCBA", "Significant clinch body strikes attempted.", "int"),
    ("sig_clinch_leg_landed", "clinch", "SCLL", "Significant clinch leg strikes landed.", "int"),
    ("sig_clinch_leg_attempted", "clinch", "SCLA", "Significant clinch leg strikes attempted.", "int"),
    ("takedowns_landed", "clinch", "TDL", "Takedowns landed.", "int"),
    ("takedowns_attempted", "clinch", "TDA", "Takedowns attempted.", "int"),
    ("takedown_slams", "clinch", "TDS", "Takedowns completed as slams.", "int"),
    ("takedown_accuracy_pct", "clinch", "TK ACC", "Takedown accuracy percentage.", "pct"),
    ("reversals", "clinch", "RV", "Reversals.", "int"),
    ("sig_ground_head_landed", "ground", "SGHL", "Significant ground head strikes landed.", "int"),
    ("sig_ground_head_attempted", "ground", "SGHA", "Significant ground head strikes attempted.", "int"),
    ("sig_ground_body_landed", "ground", "SGBL", "Significant ground body strikes landed.", "int"),
    ("sig_ground_body_attempted", "ground", "SGBA", "Significant ground body strikes attempted.", "int"),
    ("sig_ground_leg_landed", "ground", "SGLL", "Significant ground leg strikes landed.", "int"),
    ("sig_ground_leg_attempted", "ground", "SGLA", "Significant ground leg strikes attempted.", "int"),
    ("advances", "ground", "AD", "Ground position advances.", "int"),
    ("submissions_attempted", "ground", "SM", "Submission attempts.", "int"),
]


def _career_fields() -> list[pa.Field]:
    fields = [
        field("fighter_id", pa.int64(), "ESPN athlete identifier.", nullable=False),
        field("event_id", pa.int64(), "ESPN event identifier.", nullable=False),
        field("bout_id", pa.int64(), "ESPN competition identifier for the bout."),
        field("event_name", pa.string(), "Event name."),
        field("event_time", TIMESTAMP, "Event date and time in UTC."),
        field("result", pa.string(), "Result for this fighter: W, L, D, or NC."),
        field("opponent_name", pa.string(), "Opponent's name."),
    ]
    for name, _, _, comment, kind in _CAREER_STATS:
        if kind == "pair":
            fields.append(field(f"{name}_landed", pa.int32(), f"{comment} landed."))
            fields.append(field(f"{name}_attempted", pa.int32(), f"{comment} attempted."))
        elif kind == "pct":
            fields.append(field(name, PERCENT, comment))
        else:
            fields.append(field(name, pa.int32(), comment))
    return fields


CAREER_STATS_SCHEMA = pa.schema(_career_fields())


# --- events -------------------------------------------------------------------


def _competitor_name(competitor: Mapping[str, Any]) -> str | None:
    athlete = mapping(competitor.get("athlete"))
    return text(athlete.get("displayName")) or text(athlete.get("fullName"))


def _status(value: Any) -> Mapping[str, Any]:
    return mapping(mapping(value).get("type"))


def flatten_events(payload: Any, league: str) -> list[dict[str, Any]]:
    """One row per event on an ESPN scoreboard."""
    rows: list[dict[str, Any]] = []
    for value in sequence(mapping(payload).get("events")):
        event = mapping(value)
        event_id = to_int(event.get("id"))
        if event_id is None:
            continue
        competitions = sequence(event.get("competitions"))
        venue = mapping(next((mapping(v) for v in sequence(event.get("venues"))), {}))
        if not venue and competitions:
            venue = mapping(mapping(competitions[0]).get("venue"))
        address = mapping(venue.get("address"))
        status = _status(event.get("status"))
        broadcast = next(
            (text(mapping(c).get("broadcast")) for c in competitions if text(mapping(c).get("broadcast"))),
            None,
        )
        rows.append(
            {
                "league": league,
                "event_id": event_id,
                "event_name": text(event.get("name")),
                "short_name": text(event.get("shortName")),
                "start_time": to_timestamp(event.get("date")),
                "season": to_int(mapping(event.get("season")).get("year")),
                "venue": text(venue.get("fullName")),
                "city": text(address.get("city")),
                "region": text(address.get("state")),
                "country": text(address.get("country")),
                "status": text(status.get("description")),
                "event_state": text(status.get("state")),
                "completed": to_bool(status.get("completed")),
                "bout_count": len(competitions),
                "broadcast": broadcast,
            }
        )
    rows.sort(key=lambda row: (row["start_time"] is None, row["start_time"], row["event_id"]))
    return rows


# --- fightcenter bouts --------------------------------------------------------


def _referee(competition: Mapping[str, Any]) -> str | None:
    for official in sequence(competition.get("officials")):
        official = mapping(official)
        if mapping(official.get("position")).get("name") == "Referee":
            parts = [text(official.get("firstName")), text(official.get("lastName"))]
            return " ".join(part for part in parts if part) or None
    return None


def flatten_bouts(payload: Any, league: str) -> list[dict[str, Any]]:
    """One row per bout on an ESPN fightcenter page."""
    document = mapping(payload)
    event = mapping(document.get("event"))
    rows: list[dict[str, Any]] = []
    for segment_key, segment in mapping(document.get("cards")).items():
        segment = mapping(segment)
        for value in sequence(segment.get("competitions")):
            competition = mapping(value)
            bout_id = to_int(competition.get("id"))
            if bout_id is None:
                continue
            competitors = sorted(
                (mapping(c) for c in sequence(competition.get("competitors"))),
                key=lambda c: to_int(c.get("order")) or 0,
            )
            first = competitors[0] if competitors else {}
            second = competitors[1] if len(competitors) > 1 else {}
            winner = next((c for c in competitors if c.get("winner") is True), None)
            status = mapping(competition.get("status"))
            result = mapping(status.get("result"))
            completed = to_bool(_status(status).get("completed"))
            ending_round = to_int(status.get("period")) if completed is not False else None
            ending_time = text(status.get("displayClock")) if completed else None
            note = text(competition.get("note"))
            rows.append(
                {
                    "league": league,
                    "event_id": to_int(event.get("id")),
                    "event_name": text(event.get("name")),
                    "bout_id": bout_id,
                    "match_number": to_int(competition.get("matchNumber")),
                    "card_segment": text(segment.get("cardSegment")) or text(segment_key),
                    "card_segment_name": text(segment.get("displayName")),
                    "start_time": to_timestamp(competition.get("date")),
                    "weight_class": text(mapping(competition.get("type")).get("abbreviation")),
                    "note": note,
                    "title_fight": "title fight" in note.lower() if note else False,
                    "status": text(_status(status).get("description")),
                    "completed": completed,
                    "fighter1_id": to_int(first.get("id")),
                    "fighter1_name": _competitor_name(first),
                    "fighter1_record": text(first.get("displayRecord")),
                    "fighter2_id": to_int(second.get("id")),
                    "fighter2_name": _competitor_name(second),
                    "fighter2_record": text(second.get("displayRecord")),
                    "winner_id": to_int(winner.get("id")) if winner else None,
                    "winner_name": _competitor_name(winner) if winner else None,
                    "method": text(result.get("displayName")) if completed else None,
                    "method_detail": text(result.get("displayDescription")) if completed else None,
                    "ending_round": ending_round if completed else None,
                    "ending_time": ending_time,
                    "fight_duration_seconds": fight_seconds(ending_round, clock_seconds(ending_time))
                    if completed
                    else None,
                    "judges_scores": text(competition.get("judgesScores")),
                    "referee_name": _referee(competition),
                }
            )
    rows.sort(key=lambda row: (row["match_number"] is None, row["match_number"], row["bout_id"]))
    return rows


# --- fighter profile ----------------------------------------------------------

_FEET_INCHES = re.compile(r"^\s*(\d+)'\s*(\d+(?:\.\d+)?)?\"?\s*$")
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)")
_RECORD = re.compile(r"^\s*(\d+)-(\d+)(?:-(\d+))?")


def height_inches(value: Any) -> Any:
    """Convert ESPN's ``5' 9"`` display height into inches."""
    if not isinstance(value, str):
        return None
    match = _FEET_INCHES.match(value)
    if not match:
        return None
    inches = to_decimal(match.group(2) or "0")
    return to_decimal(int(match.group(1)) * 12 + (inches or 0), 1)


def leading_number(value: Any) -> Any:
    """Return the first number in a display value such as ``170 lbs`` or ``74"``."""
    if not isinstance(value, str):
        return None
    match = _NUMBER.search(value)
    return to_decimal(match.group(1), 1) if match else None


def day_month_year(value: Any) -> date | None:
    """Parse ESPN's ``D/M/YYYY`` display date of birth."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split("/")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    try:
        return date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None


def _pair(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, str):
        return None, None
    left, _, right = value.partition("-")
    return to_int(left), to_int(right)


def flatten_fighter(payload: Any) -> list[dict[str, Any]]:
    """One profile row for an ESPN athlete document (empty when not found)."""
    athlete = mapping(mapping(payload).get("athlete"))
    fighter_id = to_int(athlete.get("id"))
    if fighter_id is None:
        return []
    summary = {
        mapping(value).get("name"): text(mapping(value).get("displayValue"))
        for value in sequence(mapping(athlete.get("statsSummary")).get("statistics"))
    }
    record = summary.get("wins-losses-draws")
    match = _RECORD.match(record or "")
    ko_wins, ko_losses = _pair(summary.get("tkos-tkoLosses"))
    sub_wins, sub_losses = _pair(summary.get("submissions-submissionLosses"))
    return [
        {
            "fighter_id": fighter_id,
            "fighter_name": text(athlete.get("displayName")) or text(athlete.get("fullName")),
            "first_name": text(athlete.get("firstName")),
            "last_name": text(athlete.get("lastName")),
            "nickname": text(athlete.get("nickname")),
            "gender": text(athlete.get("gender")),
            "date_of_birth": day_month_year(athlete.get("displayDOB")),
            "age": to_int(athlete.get("age")),
            "height_in": height_inches(athlete.get("displayHeight")),
            "weight_lbs": leading_number(athlete.get("displayWeight")),
            "reach_in": leading_number(athlete.get("displayReach")),
            "stance": text(mapping(athlete.get("stance")).get("text")),
            "fighting_style": text(athlete.get("displayFightingStyle")),
            "weight_class": text(mapping(athlete.get("weightClass")).get("text")),
            "association": text(mapping(athlete.get("association")).get("name")),
            "citizenship": text(athlete.get("citizenship")),
            "active": to_bool(athlete.get("active")),
            "record": record,
            "wins": to_int(match.group(1)) if match else None,
            "losses": to_int(match.group(2)) if match else None,
            "draws": to_int(match.group(3) or 0) if match else None,
            "ko_tko_wins": ko_wins,
            "ko_tko_losses": ko_losses,
            "submission_wins": sub_wins,
            "submission_losses": sub_losses,
        }
    ]


_UID_PART = re.compile(r"~([lec]):(\d+)")


def parse_uid(uid: Any) -> dict[str, int]:
    """Split an ESPN ``s:3301~l:3321~e:600059148~c:401867788`` uid into ids."""
    if not isinstance(uid, str):
        return {}
    return {kind: int(value) for kind, value in _UID_PART.findall(uid)}


def flatten_fight_history(payload: Any) -> list[dict[str, Any]]:
    """One row per fight in an ESPN athlete's history, most recent first."""
    document = mapping(payload)
    fighter_id = to_int(mapping(document.get("athlete")).get("id"))
    if fighter_id is None:
        return []
    events_map = mapping(document.get("eventsMap"))
    rows: list[dict[str, Any]] = []
    for number, uid in enumerate(sequence(document.get("events")), start=1):
        event = mapping(events_map.get(uid))
        ids = parse_uid(uid)
        opponent = mapping(event.get("opponent"))
        status = mapping(event.get("status"))
        clock = text(status.get("displayClock"))
        league_id = ids.get("l")
        rows.append(
            {
                "fighter_id": fighter_id,
                "fight_number": number,
                "event_id": ids.get("e") or to_int(event.get("id")),
                "bout_id": ids.get("c"),
                "league_id": league_id,
                "league": LEAGUE_NAMES.get(league_id) if league_id is not None else None,
                "event_name": text(event.get("name")),
                "event_short_name": text(event.get("shortName")),
                "event_time": to_timestamp(event.get("gameDate")),
                "result": text(event.get("gameResult")),
                "opponent_id": to_int(opponent.get("id")),
                "opponent_name": text(opponent.get("displayName")),
                "method": text(mapping(status.get("result")).get("displayName")),
                "ending_round": to_int(status.get("period")),
                "ending_time": clock if clock_seconds(clock) is not None else None,
                "title_fight": to_bool(event.get("titleFight")),
            }
        )
    return rows


def _category_key(name: Any) -> str:
    return str(name or "").strip().lower()


#: Accuracy columns and the attempt columns they are computed from. ESPN reports
#: ``0%`` when nothing was attempted; that is undefined, so it becomes NULL.
_ACCURACY_ATTEMPTS = {
    "total_strike_accuracy_pct": ("total_strikes_attempted",),
    "takedown_accuracy_pct": ("takedowns_attempted",),
    **{
        f"{target}_target_pct": tuple(
            f"sig_{position}_{target}_attempted" for position in ("distance", "clinch", "ground")
        )
        for target in ("head", "body", "leg")
    },
}


def _null_accuracy_without_attempts(row: dict[str, Any]) -> None:
    for column, attempt_columns in _ACCURACY_ATTEMPTS.items():
        attempts = [row.get(name) for name in attempt_columns]
        if all(value is not None for value in attempts) and sum(attempts) == 0:
            row[column] = None


def flatten_career_stats(stats_payload: Any, athlete_payload: Any, fighter_id: int) -> list[dict[str, Any]]:
    """One per-fight statistics row, enriched with event names from the profile."""
    events_map = mapping(mapping(athlete_payload).get("eventsMap"))
    by_uid: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for category in sequence(mapping(stats_payload).get("categories")):
        category = mapping(category)
        key = _category_key(category.get("displayName") or category.get("name"))
        labels = [str(label).strip() for label in sequence(category.get("labels"))]
        for entry in sequence(category.get("statistics")):
            entry = mapping(entry)
            uid = text(entry.get("uid"))
            if uid is None:
                continue
            if uid not in by_uid:
                by_uid[uid] = {}
                order.append(uid)
            values = sequence(entry.get("stats"))
            for label, value in zip(labels, values, strict=False):
                by_uid[uid][(key, label)] = value

    rows: list[dict[str, Any]] = []
    for uid in order:
        raw = by_uid[uid]
        ids = parse_uid(uid)
        event = mapping(events_map.get(uid))
        row: dict[str, Any] = {
            "fighter_id": fighter_id,
            "event_id": ids.get("e"),
            "bout_id": ids.get("c"),
            "event_name": text(event.get("name")),
            "event_time": to_timestamp(event.get("gameDate")),
            "result": text(event.get("gameResult")),
            "opponent_name": text(mapping(event.get("opponent")).get("displayName")),
        }
        if row["event_id"] is None:
            continue
        for name, category, label, _, kind in _CAREER_STATS:
            value = raw.get((category, label))
            if kind == "pair":
                landed, attempted = landed_attempted(value)
                row[f"{name}_landed"] = landed
                row[f"{name}_attempted"] = attempted
            elif kind == "pct":
                row[name] = to_decimal(value, 2)
            else:
                row[name] = to_int(value)
        _null_accuracy_without_attempts(row)
        rows.append(row)
    return rows
