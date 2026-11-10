"""Tests for the HTTP boundary: headers, retries, caching, and error handling."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from vgi_ufc import api


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.time, "sleep", lambda seconds: None)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_honest_user_agent_and_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_FEED_BASE_URL", "https://feed.test/api/v3/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"LiveEventDetail": {"EventId": 1291, "Status": "Final"}})

    with _client(handler) as client:
        result = api.fetch_feed_event(1291, client=client)

    assert seen[0].url == "https://feed.test/api/v3/event/live/1291.json"
    assert (
        seen[0].headers["User-Agent"] == f"vgi-ufc/{api.__version__} (+https://github.com/Query-farm/vgi-ufc)"
    )
    assert result.ttl == api.FEED_FINAL_TTL


def test_responses_are_cached_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_SITE_BASE_URL", "https://espn.test/mma")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"events": []}, headers={"Cache-Control": "max-age=1"})

    with _client(handler) as client:
        first = api.fetch_scoreboard("ufc", 2025, client=client)
        second = api.fetch_scoreboard("ufc", 2025, client=client)
        api.fetch_scoreboard("ufc", 2024, client=client)

    assert len(calls) == 2
    assert "dates=2025" in calls[0] and "limit=1000" in calls[0]
    # ESPN's max-age=1 is raised to the polite floor.
    assert first.ttl == api.ESPN_SCOREBOARD_TTL.minimum
    assert second.ttl <= first.ttl


def test_cache_expiry_and_eviction(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = api._ResponseCache(max_entries=2)
    clock = [100.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    cache.store("a", api.Fetched(payload=1, ttl=10))
    cache.store("b", api.Fetched(payload=2, ttl=10))
    cache.store("zero", api.Fetched(payload=0, ttl=0))
    assert cache.get("zero") is None
    cache.store("c", api.Fetched(payload=3, ttl=10))
    assert cache.get("a") is None
    assert cache.get("b").payload == 2
    clock[0] = 111.0
    assert cache.get("b") is None


def test_ttl_policy_clamps_origin_max_age() -> None:
    policy = api.TtlPolicy(default=60, minimum=30, maximum=600)
    assert policy.resolve(None) == 60
    assert policy.resolve(1) == 30
    assert policy.resolve(604_800) == 600
    assert policy.resolve(120) == 120


def test_retries_transient_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_FEED_BASE_URL", "https://feed.test")
    statuses = iter([503, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, json={"LiveFightDetail": {"FightId": 1, "Status": "Live"}})
        return httpx.Response(status, headers={"Retry-After": "0"})

    with _client(handler) as client:
        result = api.fetch_feed_fight(1, client=client)
    assert result.payload["LiveFightDetail"]["FightId"] == 1
    assert result.ttl == api.FEED_TTL.default


def test_retries_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_FEED_BASE_URL", "https://feed.test")
    attempts = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        attempts[0] += 1
        if attempts[0] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"LiveEventDetail": {}})

    with _client(handler) as client:
        api.fetch_feed_event(5, client=client)
    assert attempts[0] == 3

    def always_fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    api.clear_cache()
    with _client(always_fail) as client, pytest.raises(httpx.ConnectError):
        api.fetch_feed_event(6, client=client)


def test_persistent_failure_is_descriptive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_WEB_BASE_URL", "https://ufc.test")
    with (
        _client(lambda request: httpx.Response(503, text="maintenance")) as client,
        pytest.raises(api.UpstreamError, match=r"ufc\.com returned HTTP 503: maintenance"),
    ):
        api.fetch_rankings_html(client=client)


def test_espn_unknown_ids_are_empty_not_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_COMMON_BASE_URL", "https://espn.test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400 if "athletes" in request.url.path else 404, json={"code": 400})

    with _client(handler) as client:
        assert api.fetch_athlete(1, client=client).payload is None
        assert api.fetch_athlete_stats(1, client=client).payload is None
        assert api.fetch_fightcenter("ufc", 1, client=client).payload is None


def test_other_client_errors_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_SITE_BASE_URL", "https://espn.test")
    with (
        _client(lambda request: httpx.Response(400, text="bad dates")) as client,
        pytest.raises(api.UpstreamError, match="ESPN site API returned HTTP 400"),
    ):
        api.fetch_scoreboard("ufc", 2025, client=client)


def test_decodes_gzip_without_content_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPN_SITE_BASE_URL", "https://espn.test")
    body = gzip.compress(json.dumps({"events": [{"id": "1"}]}).encode())
    with _client(lambda request: httpx.Response(200, content=body)) as client:
        result = api.fetch_scoreboard("pfl", 2026, client=client)
    assert result.payload["events"] == [{"id": "1"}]


def test_follows_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_WEB_BASE_URL", "https://ufc.test")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rankings":
            return httpx.Response(301, headers={"Location": "https://ufc.test/rankings/"})
        return httpx.Response(200, text="<html></html>")

    with _client(handler) as client:
        assert api.fetch_rankings_html(client=client).payload == "<html></html>"


def test_malformed_documents_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UFC_FEED_BASE_URL", "https://feed.test")
    monkeypatch.setenv("ESPN_SITE_BASE_URL", "https://espn.test")
    with _client(lambda request: httpx.Response(200, json={"unexpected": True})) as client:
        with pytest.raises(ValueError, match="no LiveEventDetail"):
            api.fetch_feed_event(1, client=client)
        with pytest.raises(ValueError, match="no LiveFightDetail"):
            api.fetch_feed_fight(1, client=client)
        with pytest.raises(ValueError, match="no events array"):
            api.fetch_scoreboard("ufc", 2025, client=client)
    with (
        _client(lambda request: httpx.Response(200, text="<html>not json")) as client,
        pytest.raises(ValueError, match="non-JSON"),
    ):
        api.fetch_feed_event(2, client=client)


def test_ids_must_be_positive() -> None:
    for call in (api.fetch_feed_event, api.fetch_feed_fight, api.fetch_athlete, api.fetch_athlete_stats):
        with pytest.raises(ValueError, match="must be positive"):
            call(0)
    with pytest.raises(ValueError, match="must be positive"):
        api.fetch_fightcenter("ufc", 0)


def test_retry_delay_honors_retry_after() -> None:
    request = httpx.Request("GET", "https://x.test")
    assert api._retry_delay(httpx.Response(429, headers={"Retry-After": "2"}, request=request), 0) == 2
    assert api._retry_delay(httpx.Response(429, headers={"Retry-After": "999"}, request=request), 0) == 30
    http_date = api._retry_delay(
        httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}, request=request), 0
    )
    assert 0 <= http_date <= api.MAX_RETRY_DELAY
    assert 0 < api._retry_delay(None, 2) <= api.MAX_RETRY_DELAY
    garbage = api._retry_delay(httpx.Response(429, headers={"Retry-After": "soon"}, request=request), 1)
    assert 0 < garbage <= api.MAX_RETRY_DELAY


def test_feed_scan_uses_shared_pool(fixture_env: dict[str, str]) -> None:
    results = api.fetch_feed_events([1290, 1291])
    assert [bool(r.payload["LiveEventDetail"]) for r in results] == [False, True]
