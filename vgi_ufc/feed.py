"""Arrow schemas and flattening for UFC's official live-data feed.

The feed publishes one JSON document per event
(``event/live/{EventId}.json``) and one per fight
(``fight/live/{FightId}.json``). Event and fight ids are sequential integers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pyarrow as pa

from vgi_ufc.convert import (
    clock_seconds,
    fight_seconds,
    mapping,
    sequence,
    text,
    to_bool,
    to_date,
    to_decimal,
    to_int,
    to_timestamp,
)
from vgi_ufc.meta import field

TIMESTAMP = pa.timestamp("us", tz="UTC")
POUNDS = pa.decimal128(5, 1)
INCHES = pa.decimal128(4, 1)
PERCENT = pa.decimal128(5, 2)

FEED_EVENT_SCHEMA = pa.schema(
    [
        field("event_id", pa.int32(), "UFC live-data event identifier (sequential integer).", nullable=False),
        field("event_name", pa.string(), "Event name, for example 'UFC 315: Muhammad vs. Della Maddalena'."),
        field("start_time", TIMESTAMP, "Scheduled event start time in UTC."),
        field("time_zone", pa.string(), "Local UTC offset label supplied by UFC, such as GMT-08:00."),
        field("status", pa.string(), "Event status: Upcoming, Live, or Final."),
        field("organization", pa.string(), "Promoting organization name."),
        field("venue", pa.string(), "Venue name."),
        field("city", pa.string(), "Venue city."),
        field("region", pa.string(), "Venue state, province, or region, when supplied."),
        field("country", pa.string(), "Venue country."),
        field("fight_count", pa.int32(), "Number of fights currently on the card."),
        field("main_event", pa.string(), "Main event as 'Red fighter vs. Blue fighter'."),
    ]
)

FIGHT_CARD_SCHEMA = pa.schema(
    [
        field("event_id", pa.int32(), "UFC live-data event identifier."),
        field("event_name", pa.string(), "Event name."),
        field("event_start_time", TIMESTAMP, "Scheduled event start time in UTC."),
        field("fight_id", pa.int32(), "UFC live-data fight identifier.", nullable=False),
        field("fight_order", pa.int32(), "Running order on the card; 1 is the main event."),
        field(
            "card_segment",
            pa.string(),
            "Card segment: Main, Prelims1 (prelims), or Prelims2 (early prelims).",
        ),
        field("card_segment_start_time", TIMESTAMP, "Scheduled start of this card segment in UTC."),
        field("broadcaster", pa.string(), "Broadcaster or streaming service for the segment."),
        field("status", pa.string(), "Fight status: Upcoming, Live, or Final."),
        field("weight_class", pa.string(), "Weight class description, such as Welterweight or Catch Weight."),
        field("weight_class_abbreviation", pa.string(), "UFC weight class abbreviation, such as WW."),
        field("weight_range", pa.string(), "Weight range in pounds for the class, such as '156-170'."),
        field("catch_weight_lbs", POUNDS, "Agreed catch weight in pounds, when the bout is at catch weight."),
        field("scheduled_rounds", pa.int32(), "Number of scheduled rounds (3 or 5)."),
        field("rule_set", pa.string(), "Rule set description, such as '5 Rnd (5-5-5-5-5)'."),
        field("referee_name", pa.string(), "Assigned referee."),
        field("red_fighter_id", pa.int32(), "UFC fighter identifier in the red corner."),
        field("red_fighter_name", pa.string(), "Red-corner fighter's full name."),
        field(
            "red_record", pa.string(), "Red-corner professional record as W-L-D when the card was published."
        ),
        field("blue_fighter_id", pa.int32(), "UFC fighter identifier in the blue corner."),
        field("blue_fighter_name", pa.string(), "Blue-corner fighter's full name."),
        field(
            "blue_record",
            pa.string(),
            "Blue-corner professional record as W-L-D when the card was published.",
        ),
    ]
)

CARD_FIGHTER_SCHEMA = pa.schema(
    [
        field("event_id", pa.int32(), "UFC live-data event identifier."),
        field("fight_id", pa.int32(), "UFC live-data fight identifier.", nullable=False),
        field("fight_order", pa.int32(), "Running order on the card; 1 is the main event."),
        field("fighter_id", pa.int32(), "UFC fighter identifier.", nullable=False),
        field("corner", pa.string(), "Corner: Red or Blue."),
        field("fighter_name", pa.string(), "Fighter's full name."),
        field("nickname", pa.string(), "Fighter's nickname, when known."),
        field(
            "outcome",
            pa.string(),
            "Bout outcome for this fighter: Win, Loss, Draw, or NC; null before the fight.",
        ),
        field("wins", pa.int32(), "Professional wins in the published record."),
        field("losses", pa.int32(), "Professional losses in the published record."),
        field("draws", pa.int32(), "Professional draws in the published record."),
        field("no_contests", pa.int32(), "Professional no contests in the published record."),
        field("date_of_birth", pa.date32(), "Date of birth."),
        field("age", pa.int32(), "Age in years as reported by UFC."),
        field("stance", pa.string(), "Fighting stance, such as Orthodox or Southpaw."),
        field("height_in", INCHES, "Height in inches."),
        field("reach_in", INCHES, "Reach in inches."),
        field("weigh_in_lbs", POUNDS, "Official weigh-in weight in pounds, when published."),
        field("born_city", pa.string(), "City of birth."),
        field("born_country", pa.string(), "Country of birth."),
        field("fighting_out_of_city", pa.string(), "City the fighter trains or fights out of."),
        field("fighting_out_of_country", pa.string(), "Country the fighter trains or fights out of."),
        field(
            "performance_of_the_night",
            pa.bool_(),
            "Whether the fighter earned a Performance of the Night bonus.",
        ),
        field("ufc_athlete_url", pa.string(), "Fighter's ufc.com page (lower-case; joins current_rankings)."),
    ]
)

FIGHT_RESULT_SCHEMA = pa.schema(
    [
        field("event_id", pa.int32(), "UFC live-data event identifier."),
        field("fight_id", pa.int32(), "UFC live-data fight identifier.", nullable=False),
        field("fight_order", pa.int32(), "Running order on the card; 1 is the main event."),
        field("card_segment", pa.string(), "Card segment: Main, Prelims1, or Prelims2."),
        field("weight_class", pa.string(), "Weight class description."),
        field("status", pa.string(), "Fight status: Upcoming, Live, or Final."),
        field(
            "outcome", pa.string(), "win when one fighter won; otherwise Draw, NC, or null if not yet fought."
        ),
        field("winner_fighter_id", pa.int32(), "UFC fighter identifier of the winner."),
        field("winner_name", pa.string(), "Winner's full name."),
        field("loser_fighter_id", pa.int32(), "UFC fighter identifier of the loser."),
        field("loser_name", pa.string(), "Loser's full name."),
        field("method", pa.string(), "Result method, such as KO/TKO, Submission, or Decision - Unanimous."),
        field("ending_round", pa.int32(), "Round in which the fight ended."),
        field("ending_time", pa.string(), "Clock time within the ending round, as M:SS."),
        field("ending_time_seconds", pa.int32(), "Seconds elapsed in the ending round."),
        field(
            "fight_duration_seconds", pa.int32(), "Total fight time in seconds, assuming five-minute rounds."
        ),
        field("ending_strike", pa.string(), "Finishing strike for a KO/TKO, such as Punch or Knee."),
        field("ending_target", pa.string(), "Target of the finishing strike, such as Head."),
        field("ending_position", pa.string(), "Position at the finish, such as In Clinch or On Ground."),
        field("ending_submission", pa.string(), "Submission hold for a submission finish."),
        field("ending_notes", pa.string(), "Free-text result notes from UFC, when supplied."),
        field(
            "judges_scores",
            pa.string(),
            "Judges' totals as 'winner-loser' (red-blue when no winner), comma separated.",
        ),
        field("fight_of_the_night", pa.bool_(), "Whether the bout won Fight of the Night."),
        field(
            "performance_bonus_names",
            pa.string(),
            "Fighters who earned Performance of the Night, comma separated.",
        ),
        field("referee_name", pa.string(), "Referee."),
    ]
)

SCORECARD_SCHEMA = pa.schema(
    [
        field("fight_id", pa.int32(), "UFC live-data fight identifier.", nullable=False),
        field("judge_id", pa.int32(), "UFC judge identifier.", nullable=False),
        field("judge_name", pa.string(), "Judge's full name."),
        field("round_number", pa.int32(), "Round scored.", nullable=False),
        field("red_fighter_id", pa.int32(), "Red-corner UFC fighter identifier."),
        field("red_fighter_name", pa.string(), "Red-corner fighter's full name."),
        field(
            "red_score", pa.int32(), "Points awarded to the red corner for the round (10-point must system)."
        ),
        field("blue_fighter_id", pa.int32(), "Blue-corner UFC fighter identifier."),
        field("blue_fighter_name", pa.string(), "Blue-corner fighter's full name."),
        field("blue_score", pa.int32(), "Points awarded to the blue corner for the round."),
    ]
)

_STAT_FIELDS: list[tuple[str, str, str]] = [
    ("knockdowns", "Knockdowns", "Knockdowns scored."),
    ("total_strikes_landed", "TotalStrikesLanded", "Total strikes landed, significant and non-significant."),
    ("total_strikes_attempted", "TotalStrikesAttempted", "Total strikes attempted."),
    ("sig_strikes_landed", "SigStrikesLanded", "Significant strikes landed."),
    ("sig_strikes_attempted", "SigStrikesAttempted", "Significant strikes attempted."),
    ("sig_head_landed", "SigHeadStrikesLanded", "Significant strikes landed to the head."),
    ("sig_head_attempted", "SigHeadStrikesAttempted", "Significant strikes attempted to the head."),
    ("sig_body_landed", "SigBodyStrikesLanded", "Significant strikes landed to the body."),
    ("sig_body_attempted", "SigBodyStrikesAttempted", "Significant strikes attempted to the body."),
    ("sig_leg_landed", "SigLegStrikesLanded", "Significant strikes landed to the legs."),
    ("sig_leg_attempted", "SigLegStrikesAttempted", "Significant strikes attempted to the legs."),
    ("sig_distance_landed", "SigDistanceStrikesLanded", "Significant strikes landed at distance."),
    ("sig_distance_attempted", "SigDistanceStrikesAttempted", "Significant strikes attempted at distance."),
    ("sig_clinch_landed", "SigClinchStrikesLanded", "Significant strikes landed in the clinch."),
    ("sig_clinch_attempted", "SigClinchStrikesAttempted", "Significant strikes attempted in the clinch."),
    ("sig_ground_landed", "SigGroundStrikesLanded", "Significant strikes landed on the ground."),
    ("sig_ground_attempted", "SigGroundStrikesAttempted", "Significant strikes attempted on the ground."),
    ("takedowns_landed", "TakedownsLanded", "Takedowns landed."),
    ("takedowns_attempted", "TakedownsAttempted", "Takedowns attempted."),
    ("reversals", "Reversals", "Reversals."),
    ("submissions_attempted", "SubmissionsAttempted", "Submission attempts."),
]

_TIME_FIELDS: list[tuple[str, str, str]] = [
    ("control_seconds", "ControlTime", "Seconds of positional control."),
    ("distance_seconds", "DistanceTime", "Seconds spent fighting at distance."),
    ("clinch_seconds", "ClinchTime", "Seconds spent in the clinch."),
    ("ground_seconds", "GroundTime", "Seconds spent on the ground."),
]


def _stats_schema(*, per_round: bool) -> pa.Schema:
    fields = [
        field("fight_id", pa.int32(), "UFC live-data fight identifier.", nullable=False),
        field("event_id", pa.int32(), "UFC live-data event identifier."),
        field("fighter_id", pa.int32(), "UFC fighter identifier.", nullable=False),
        field("fighter_name", pa.string(), "Fighter's full name."),
        field("corner", pa.string(), "Corner: Red or Blue."),
        field("outcome", pa.string(), "Bout outcome for this fighter: Win, Loss, Draw, or NC."),
    ]
    if per_round:
        fields.append(field("round_number", pa.int32(), "Round number.", nullable=False))
    for name, _, comment in _STAT_FIELDS:
        fields.append(field(name, pa.int32(), comment))
        if name == "sig_strikes_attempted":
            fields.append(
                field(
                    "sig_strike_accuracy_pct", PERCENT, "Significant strike accuracy as a percentage (0-100)."
                )
            )
        elif name == "takedowns_attempted":
            fields.append(
                field("takedown_accuracy_pct", PERCENT, "Takedown accuracy as a percentage (0-100).")
            )
    fields += [field(name, pa.int32(), comment) for name, _, comment in _TIME_FIELDS]
    return pa.schema(fields)


FIGHT_STATS_SCHEMA = _stats_schema(per_round=False)
ROUND_STATS_SCHEMA = _stats_schema(per_round=True)


def _full_name(name: Mapping[str, Any]) -> str | None:
    parts = [text(name.get("FirstName")), text(name.get("LastName"))]
    joined = " ".join(part for part in parts if part)
    return joined or None


def _record(record: Mapping[str, Any]) -> str | None:
    wins, losses, draws = (to_int(record.get(key)) for key in ("Wins", "Losses", "Draws"))
    if wins is None or losses is None:
        return None
    return f"{wins}-{losses}-{draws or 0}"


def _corner(fighters: list[Any], corner: str) -> Mapping[str, Any]:
    for value in fighters:
        if mapping(value).get("Corner") == corner:
            return mapping(value)
    return {}


def _person(value: Mapping[str, Any]) -> str | None:
    parts = [text(value.get("FirstName")), text(value.get("LastName"))]
    joined = " ".join(part for part in parts if part)
    return joined or None


def event_detail(payload: Any) -> Mapping[str, Any]:
    """Return the event object from a feed document, or an empty mapping."""
    return mapping(mapping(payload).get("LiveEventDetail"))


def fights(payload: Any) -> list[Mapping[str, Any]]:
    """Return the fight objects on an event document, in running order."""
    card = [mapping(value) for value in sequence(event_detail(payload).get("FightCard"))]
    return sorted(card, key=lambda value: to_int(value.get("FightOrder")) or 10_000)


def flatten_feed_event(payload: Any) -> list[dict[str, Any]]:
    """Flatten an event document into one summary row (empty for an unknown id)."""
    event = event_detail(payload)
    event_id = to_int(event.get("EventId"))
    if event_id is None:
        return []
    location = mapping(event.get("Location"))
    card = fights(payload)
    main = card[0] if card else {}
    fighters = sequence(main.get("Fighters"))
    red = _full_name(mapping(_corner(fighters, "Red").get("Name")))
    blue = _full_name(mapping(_corner(fighters, "Blue").get("Name")))
    return [
        {
            "event_id": event_id,
            "event_name": text(event.get("Name")),
            "start_time": to_timestamp(event.get("StartTime")),
            "time_zone": text(event.get("TimeZone")),
            "status": text(event.get("Status")),
            "organization": text(mapping(event.get("Organization")).get("Name")),
            "venue": text(location.get("Venue")),
            "city": text(location.get("City")),
            "region": text(location.get("State")),
            "country": text(location.get("Country")),
            "fight_count": len(card),
            "main_event": f"{red} vs. {blue}" if red and blue else None,
        }
    ]


def flatten_fight_card(payload: Any) -> list[dict[str, Any]]:
    """One row per fight on an event card."""
    event = event_detail(payload)
    rows: list[dict[str, Any]] = []
    for fight in fights(payload):
        fight_id = to_int(fight.get("FightId"))
        if fight_id is None:
            continue
        fighters = sequence(fight.get("Fighters"))
        red, blue = _corner(fighters, "Red"), _corner(fighters, "Blue")
        weight = mapping(fight.get("WeightClass"))
        rules = mapping(fight.get("RuleSet"))
        rows.append(
            {
                "event_id": to_int(event.get("EventId")),
                "event_name": text(event.get("Name")),
                "event_start_time": to_timestamp(event.get("StartTime")),
                "fight_id": fight_id,
                "fight_order": to_int(fight.get("FightOrder")),
                "card_segment": text(fight.get("CardSegment")),
                "card_segment_start_time": to_timestamp(fight.get("CardSegmentStartTime")),
                "broadcaster": text(fight.get("CardSegmentBroadcaster")),
                "status": text(fight.get("Status")),
                "weight_class": text(weight.get("Description")),
                "weight_class_abbreviation": text(weight.get("Abbreviation")),
                "weight_range": text(weight.get("Weight")),
                "catch_weight_lbs": to_decimal(weight.get("CatchWeight"), 1),
                "scheduled_rounds": to_int(rules.get("PossibleRounds")),
                "rule_set": text(rules.get("Description")),
                "referee_name": _person(mapping(fight.get("Referee"))),
                "red_fighter_id": to_int(red.get("FighterId")),
                "red_fighter_name": _full_name(mapping(red.get("Name"))),
                "red_record": _record(mapping(red.get("Record"))),
                "blue_fighter_id": to_int(blue.get("FighterId")),
                "blue_fighter_name": _full_name(mapping(blue.get("Name"))),
                "blue_record": _record(mapping(blue.get("Record"))),
            }
        )
    return rows


def _fighter_row(fighter: Mapping[str, Any]) -> dict[str, Any]:
    name = mapping(fighter.get("Name"))
    record = mapping(fighter.get("Record"))
    born = mapping(fighter.get("Born"))
    out_of = mapping(fighter.get("FightingOutOf"))
    return {
        "fighter_id": to_int(fighter.get("FighterId")),
        "corner": text(fighter.get("Corner")),
        "fighter_name": _full_name(name),
        "nickname": text(name.get("NickName")),
        "outcome": text(mapping(fighter.get("Outcome")).get("Outcome")),
        "wins": to_int(record.get("Wins")),
        "losses": to_int(record.get("Losses")),
        "draws": to_int(record.get("Draws")),
        "no_contests": to_int(record.get("NoContests")),
        "date_of_birth": to_date(fighter.get("DOB")),
        "age": to_int(fighter.get("Age")),
        "stance": text(fighter.get("Stance")),
        "height_in": to_decimal(fighter.get("Height"), 1),
        "reach_in": to_decimal(fighter.get("Reach"), 1),
        "weigh_in_lbs": to_decimal(fighter.get("WeighIn"), 1),
        "born_city": text(born.get("City")),
        "born_country": text(born.get("Country")),
        "fighting_out_of_city": text(out_of.get("City")),
        "fighting_out_of_country": text(out_of.get("Country")),
        "performance_of_the_night": to_bool(fighter.get("PerformanceOfTheNight")),
        "ufc_athlete_url": _athlete_url(text(fighter.get("UFCLink"))),
    }


def _athlete_url(url: str | None) -> str | None:
    """Normalize a feed ``UFCLink`` to the https, lower-case slug ufc.com redirects to.

    The lower-case form matches ``current_rankings.ufc_athlete_url`` for the same fighter.
    """
    if not url:
        return url
    if url.startswith("http://"):
        url = "https://" + url.removeprefix("http://")
    prefix, marker, slug = url.partition("/athlete/")
    return f"{prefix}{marker}{slug.lower()}" if marker else url


def flatten_card_fighters(payload: Any) -> list[dict[str, Any]]:
    """One row per fighter per fight on an event card."""
    event_id = to_int(event_detail(payload).get("EventId"))
    rows: list[dict[str, Any]] = []
    for fight in fights(payload):
        fight_id = to_int(fight.get("FightId"))
        for fighter in sequence(fight.get("Fighters")):
            row = _fighter_row(mapping(fighter))
            if fight_id is None or row["fighter_id"] is None:
                continue
            rows.append(
                {
                    "event_id": event_id,
                    "fight_id": fight_id,
                    "fight_order": to_int(fight.get("FightOrder")),
                    **row,
                }
            )
    return rows


def _judges_scores(result: Mapping[str, Any], first_id: int | None, second_id: int | None) -> str | None:
    totals: list[str] = []
    for judge in sequence(result.get("FightScores")):
        scores = {
            to_int(mapping(value).get("FighterId")): to_int(mapping(value).get("Score"))
            for value in sequence(mapping(judge).get("Fighters"))
        }
        first, second = scores.get(first_id), scores.get(second_id)
        if first is not None and second is not None:
            totals.append(f"{first}-{second}")
    return ", ".join(totals) or None


def _result_row(fight: Mapping[str, Any], event_id: int | None) -> dict[str, Any] | None:
    fight_id = to_int(fight.get("FightId"))
    if fight_id is None:
        return None
    fighters = [mapping(value) for value in sequence(fight.get("Fighters"))]
    outcomes = {to_int(f.get("FighterId")): text(mapping(f.get("Outcome")).get("Outcome")) for f in fighters}
    winner = next((f for f in fighters if outcomes.get(to_int(f.get("FighterId"))) == "Win"), None)
    loser = next((f for f in fighters if outcomes.get(to_int(f.get("FighterId"))) == "Loss"), None)
    red, blue = _corner(fighters, "Red"), _corner(fighters, "Blue")
    if winner is not None:
        outcome = "win"
        first, second = winner, loser or (blue if winner is red else red)
    else:
        observed = {value for value in outcomes.values() if value}
        outcome = observed.pop() if len(observed) == 1 else None
        first, second = red, blue
    result = mapping(fight.get("Result"))
    ending_round = to_int(result.get("EndingRound"))
    ending_time = text(result.get("EndingTime"))
    ending_seconds = clock_seconds(ending_time)
    bonus = [_full_name(mapping(f.get("Name"))) for f in fighters if f.get("PerformanceOfTheNight") is True]
    return {
        "event_id": event_id,
        "fight_id": fight_id,
        "fight_order": to_int(fight.get("FightOrder")),
        "card_segment": text(fight.get("CardSegment")),
        "weight_class": text(mapping(fight.get("WeightClass")).get("Description")),
        "status": text(fight.get("Status")),
        "outcome": outcome,
        "winner_fighter_id": to_int(winner.get("FighterId")) if winner else None,
        "winner_name": _full_name(mapping(winner.get("Name"))) if winner else None,
        "loser_fighter_id": to_int(loser.get("FighterId")) if loser else None,
        "loser_name": _full_name(mapping(loser.get("Name"))) if loser else None,
        "method": text(result.get("Method")),
        "ending_round": ending_round,
        "ending_time": ending_time,
        "ending_time_seconds": ending_seconds,
        "fight_duration_seconds": fight_seconds(ending_round, ending_seconds),
        "ending_strike": text(result.get("EndingStrike")),
        "ending_target": text(result.get("EndingTarget")),
        "ending_position": text(result.get("EndingPosition")),
        "ending_submission": text(result.get("EndingSubmission")),
        "ending_notes": text(result.get("EndingNotes")),
        "judges_scores": _judges_scores(
            result, to_int(mapping(first).get("FighterId")), to_int(mapping(second).get("FighterId"))
        ),
        "fight_of_the_night": to_bool(result.get("FightOfTheNight")),
        "performance_bonus_names": ", ".join(name for name in bonus if name) or None,
        "referee_name": _person(mapping(fight.get("Referee"))),
    }


def flatten_fight_results(payload: Any) -> list[dict[str, Any]]:
    """One result row per fight on an event card."""
    event_id = to_int(event_detail(payload).get("EventId"))
    return [row for fight in fights(payload) if (row := _result_row(fight, event_id)) is not None]


def fight_detail(payload: Any) -> Mapping[str, Any]:
    """Return the fight object from a fight document, or an empty mapping."""
    return mapping(mapping(payload).get("LiveFightDetail"))


def flatten_scorecards(payload: Any) -> list[dict[str, Any]]:
    """One row per judge per round for a decision (empty for a finish)."""
    fight = fight_detail(payload)
    fight_id = to_int(fight.get("FightId"))
    if fight_id is None:
        return []
    fighters = sequence(fight.get("Fighters"))
    red, blue = _corner(fighters, "Red"), _corner(fighters, "Blue")
    red_id, blue_id = to_int(red.get("FighterId")), to_int(blue.get("FighterId"))
    rows: list[dict[str, Any]] = []
    for judge in sequence(mapping(fight.get("Result")).get("RoundScores")):
        judge = mapping(judge)
        judge_id = to_int(judge.get("JudgeId"))
        judge_name = _person(
            {"FirstName": judge.get("JudgeFirstName"), "LastName": judge.get("JudgeLastName")}
        )
        for round_score in sequence(judge.get("Rounds")):
            round_score = mapping(round_score)
            number = to_int(round_score.get("RoundNumber"))
            if judge_id is None or number is None:
                continue
            scores = {
                to_int(mapping(value).get("FighterId")): to_int(mapping(value).get("Score"))
                for value in sequence(round_score.get("Fighters"))
            }
            rows.append(
                {
                    "fight_id": fight_id,
                    "judge_id": judge_id,
                    "judge_name": judge_name,
                    "round_number": number,
                    "red_fighter_id": red_id,
                    "red_fighter_name": _full_name(mapping(red.get("Name"))),
                    "red_score": scores.get(red_id),
                    "blue_fighter_id": blue_id,
                    "blue_fighter_name": _full_name(mapping(blue.get("Name"))),
                    "blue_score": scores.get(blue_id),
                }
            )
    return rows


def _stat_values(stats: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {name: to_int(stats.get(key)) for name, key, _ in _STAT_FIELDS}
    values["sig_strike_accuracy_pct"] = to_decimal(stats.get("SigStrikesAccuracy"), 2)
    values["takedown_accuracy_pct"] = to_decimal(stats.get("TakedownsAccuracy"), 2)
    values.update({name: clock_seconds(stats.get(key)) for name, key, _ in _TIME_FIELDS})
    return values


def _fighter_context(fight: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    context: dict[int, dict[str, Any]] = {}
    for value in sequence(fight.get("Fighters")):
        fighter = mapping(value)
        fighter_id = to_int(fighter.get("FighterId"))
        if fighter_id is not None:
            context[fighter_id] = {
                "fighter_name": _full_name(mapping(fighter.get("Name"))),
                "corner": text(fighter.get("Corner")),
                "outcome": text(mapping(fighter.get("Outcome")).get("Outcome")),
            }
    return context


def flatten_fight_stats(payload: Any) -> list[dict[str, Any]]:
    """One whole-fight statistics row per fighter."""
    fight = fight_detail(payload)
    fight_id = to_int(fight.get("FightId"))
    if fight_id is None:
        return []
    event_id = to_int(mapping(fight.get("Event")).get("EventId"))
    context = _fighter_context(fight)
    rows: list[dict[str, Any]] = []
    for value in sequence(fight.get("FightStats")):
        stats = mapping(value)
        fighter_id = to_int(stats.get("FighterId"))
        if fighter_id is None:
            continue
        rows.append(
            {
                "fight_id": fight_id,
                "event_id": event_id,
                "fighter_id": fighter_id,
                **context.get(fighter_id, {}),
                **_stat_values(stats),
            }
        )
    return rows


def flatten_round_stats(payload: Any) -> list[dict[str, Any]]:
    """One statistics row per fighter per round."""
    fight = fight_detail(payload)
    fight_id = to_int(fight.get("FightId"))
    if fight_id is None:
        return []
    event_id = to_int(mapping(fight.get("Event")).get("EventId"))
    context = _fighter_context(fight)
    rows: list[dict[str, Any]] = []
    for value in sequence(fight.get("RoundStats")):
        entry = mapping(value)
        fighter_id = to_int(entry.get("FighterId"))
        if fighter_id is None:
            continue
        for round_value in sequence(entry.get("Rounds")):
            stats = mapping(round_value)
            number = to_int(stats.get("RoundNumber"))
            if number is None:
                continue
            rows.append(
                {
                    "fight_id": fight_id,
                    "event_id": event_id,
                    "fighter_id": fighter_id,
                    **context.get(fighter_id, {}),
                    "round_number": number,
                    **_stat_values(stats),
                }
            )
    rows.sort(key=lambda row: (row["round_number"], row.get("corner") != "Red"))
    return rows
