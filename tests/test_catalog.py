"""Tests for the SQL-facing catalog shape and discovery metadata."""

import json
from pathlib import Path

from vgi_ufc.event_functions import CurrentSeasonEventsFunction, EventsFunction, UpcomingEventsFunction
from vgi_ufc.ranking_functions import CurrentRankingsFunction
from vgi_ufc.worker import UFC_CATALOG

ROOT = Path(__file__).resolve().parent.parent


def test_catalog_surface() -> None:
    schema = UFC_CATALOG.schemas[0]
    assert UFC_CATALOG.name == "ufc"
    assert schema.path == ["main"]
    assert {function.Meta.name for function in schema.functions} == {
        "all_current_rankings",
        "all_upcoming_events",
        "all_current_season_events",
        "events",
        "event_bouts",
        "feed_events",
        "fight_card",
        "card_fighters",
        "fight_results",
        "fight_scorecards",
        "fight_stats",
        "fight_round_stats",
        "fighter",
        "fighter_fight_history",
        "fighter_career_stats",
    }
    assert {table.name: table.function for table in schema.tables} == {
        "current_rankings": CurrentRankingsFunction,
        "upcoming_events": UpcomingEventsFunction,
        "current_season_events": CurrentSeasonEventsFunction,
    }


def test_events_arguments_are_named_and_optional() -> None:
    parameters = {parameter.name: parameter for parameter in EventsFunction.get_metadata().parameters}
    assert set(parameters) == {"season", "league"}
    assert all(not parameter.required for parameter in parameters.values())


def _key_of(table, kind: str) -> list[tuple[str, ...]]:
    return [
        tuple(name for path in record.definition.column_paths for name in path)
        for record in table.constraints
        if record.definition.kind == kind
    ]


def test_table_keys() -> None:
    tables = {table.name: table for table in UFC_CATALOG.schemas[0].tables}
    assert _key_of(tables["current_rankings"], "PRIMARY_KEY") == [("division", "fighter_slug")]
    assert _key_of(tables["upcoming_events"], "PRIMARY_KEY") == [("event_id",)]
    assert _key_of(tables["current_season_events"], "NOT_NULL") == [("event_id",)]


def test_every_function_documents_its_result_columns() -> None:
    for function in UFC_CATALOG.schemas[0].functions:
        tags = function.Meta.tags
        columns = json.loads(tags["vgi.result_columns_schema"])
        assert [column["name"] for column in columns] == function.FIXED_SCHEMA.names
        assert all(column["description"] for column in columns)
        assert tags["vgi.doc_llm"] and tags["vgi.doc_md"] and tags["vgi.title"]
        assert json.loads(tags["vgi.example_queries"])
        assert function.Meta.examples


def test_catalog_discovery_contract_is_public_and_machine_readable() -> None:
    tags = UFC_CATALOG.tags
    for key in ("vgi.title", "vgi.subtitle", "vgi.doc_llm", "vgi.doc_md", "vgi.keywords", "vgi.copyright"):
        assert tags[key]
    assert "Not affiliated" in tags["vgi.copyright"]
    examples = json.loads(tags["vgi.executable_examples"])
    tasks = json.loads(tags["vgi.agent_test_tasks"])
    assert examples
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert 6 <= len(tasks) <= 10
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)


def test_agent_test_grader_covers_every_public_task() -> None:
    text = (ROOT / "vgi-agent-tests.yaml").read_text()
    graded = {line.split(":", 1)[1].strip() for line in text.splitlines() if line.startswith("  - name:")}
    public = {task["name"] for task in json.loads(UFC_CATALOG.tags["vgi.agent_test_tasks"])}
    assert graded == public
    assert "check_sql" in text


def test_native_examples_match_described_tag_examples() -> None:
    """vgi-lint merges Meta.examples with vgi.example_queries by SQL; unmatched ones lack a description."""
    for function in UFC_CATALOG.schemas[0].functions:
        described = {
            " ".join(e["sql"].split()).lower() for e in json.loads(function.Meta.tags["vgi.example_queries"])
        }
        for example in function.Meta.examples:
            assert " ".join(example.sql.split()).lower() in described, function.Meta.name


def test_metadata_values_fit_agent_context_budget() -> None:
    for function in UFC_CATALOG.schemas[0].functions:
        for key, value in function.Meta.tags.items():
            assert len(value) <= 4_000, (function.Meta.name, key)
