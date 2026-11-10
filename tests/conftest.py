"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixture_server import serve_fixtures  # noqa: E402

from vgi_ufc import api  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Every test starts and ends with an empty response cache."""
    api.clear_cache()
    yield
    api.clear_cache()


@pytest.fixture
def fixture_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Point every upstream at the local fixture server."""
    with serve_fixtures() as env:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        yield env
