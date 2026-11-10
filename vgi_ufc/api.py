"""Small, read-only, caching HTTP client for the UFC feed, ESPN MMA, and ufc.com.

Every outbound request in the package goes through :func:`fetch`. It applies an
honest User-Agent, bounded timeouts, a total query deadline, a process-wide
concurrency limit, retries with backoff for 429 and transient 5xx responses,
redirect following, and an in-process TTL cache so repeated queries do not
re-request the same upstream document.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_ufc import __version__

USER_AGENT = f"vgi-ufc/{__version__} (+https://github.com/Query-farm/vgi-ufc)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0
MAX_CONCURRENT_REQUESTS = 4
CACHE_MAX_ENTRIES = 512

#: Upstream roots. Each can be overridden by an environment variable so tests
#: can point the worker at a local fixture server.
SOURCES: dict[str, tuple[str, str]] = {
    "ufc_feed": ("UFC_FEED_BASE_URL", "https://d29dxerjsp82wz.cloudfront.net/api/v3"),
    "espn_site": ("ESPN_SITE_BASE_URL", "https://site.api.espn.com/apis/site/v2/sports/mma"),
    "espn_common": ("ESPN_COMMON_BASE_URL", "https://site.web.api.espn.com/apis/common/v3/sports/mma"),
    "ufc_web": ("UFC_WEB_BASE_URL", "https://www.ufc.com"),
}

SOURCE_LABELS = {
    "ufc_feed": "UFC live-data feed",
    "espn_site": "ESPN site API",
    "espn_common": "ESPN common API",
    "ufc_web": "ufc.com",
}

logger = logging.getLogger(__name__)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)


class UpstreamError(RuntimeError):
    """A failed response from one of the upstream sources."""

    def __init__(self, source: str, status: int, body: str) -> None:
        label = SOURCE_LABELS.get(source, source)
        super().__init__(f"{label} returned HTTP {status}: {body[:400]}")
        self.source = source
        self.status = status


@dataclass(frozen=True, slots=True)
class TtlPolicy:
    """How long a response may be reused, in seconds.

    ``default`` applies when the origin sends no ``max-age``. An origin
    ``max-age`` is honored but clamped to ``[minimum, maximum]``: the floor keeps
    ESPN's ``max-age=1`` from turning every query into a fresh request, and the
    ceiling keeps ufc.com's week-long HTML lifetime from hiding ranking updates.
    """

    default: int
    minimum: int = 30
    maximum: int = 3_600

    def resolve(self, header_max_age: int | None) -> int:
        """Return the effective lifetime for a response."""
        if header_max_age is None:
            return self.default
        return max(self.minimum, min(header_max_age, self.maximum))


@dataclass(frozen=True, slots=True)
class Fetched:
    """A decoded upstream document plus the lifetime it was cached for."""

    payload: Any
    ttl: int
    status: int = 200


class _ResponseCache:
    """A small thread-safe LRU cache with per-entry expiry."""

    def __init__(self, max_entries: int) -> None:
        self._entries: OrderedDict[str, tuple[float, Fetched]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_entries = max_entries

    def get(self, key: str) -> Fetched | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            remaining = max(1, int(expires_at - time.monotonic()))
            return Fetched(payload=value.payload, ttl=min(value.ttl, remaining), status=value.status)

    def store(self, key: str, value: Fetched) -> None:
        if value.ttl <= 0:
            return
        with self._lock:
            self._entries[key] = (time.monotonic() + value.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_cache = _ResponseCache(CACHE_MAX_ENTRIES)


def clear_cache() -> None:
    """Drop every cached upstream response (used by tests)."""
    _cache.clear()


def base_url(source: str) -> str:
    """Return a source's root URL, honoring its environment override."""
    variable, default = SOURCES[source]
    return os.environ.get(variable, default).rstrip("/")


def _max_age(response: httpx.Response) -> int | None:
    match = _MAX_AGE.search(response.headers.get("cache-control", ""))
    return int(match.group(1)) if match else None


@contextmanager
def _client(client: httpx.Client | None):
    """Reuse one connection pool for every request in a logical fetch."""
    if client is not None:
        yield client
        return
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as owned:
        yield owned


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.25 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _request(
    source: str,
    path: str,
    params: Mapping[str, str | int] | None,
    *,
    accept: str,
    client: httpx.Client,
    deadline: float,
) -> httpx.Response:
    """Issue one GET, retrying transport failures, 429 and transient 5xx."""
    url = f"{base_url(source)}/{path.lstrip('/')}"
    label = SOURCE_LABELS[source]
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{label} query exceeded {QUERY_TIMEOUT:g} seconds")
        started = time.monotonic()
        try:
            if not _request_slots.acquire(timeout=remaining):
                raise TimeoutError(f"{label} query exceeded {QUERY_TIMEOUT:g} seconds")
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{label} query exceeded {QUERY_TIMEOUT:g} seconds")
                response = client.get(
                    url,
                    params=dict(params or {}),
                    headers={"Accept": accept, "User-Agent": USER_AGENT},
                    timeout=httpx.Timeout(min(30.0, remaining), connect=min(10.0, remaining)),
                    follow_redirects=True,
                )
            finally:
                _request_slots.release()
        except httpx.TransportError:
            logger.warning(
                "ufc_upstream_transport_error source=%s path=%s attempt=%d duration_ms=%d",
                source,
                path,
                attempt + 1,
                round((time.monotonic() - started) * 1_000),
            )
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        logger.debug(
            "ufc_upstream_response source=%s path=%s status=%d attempt=%d duration_ms=%d",
            source,
            path,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            return response
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "ufc_upstream_retry source=%s path=%s status=%d attempt=%d delay_seconds=%.3f",
            source,
            path,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("retry loop exited without a response")


def _body_bytes(response: httpx.Response) -> bytes:
    """Return the body, decompressing gzip that arrived without Content-Encoding."""
    content = response.content
    if content[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(content)
        except (OSError, EOFError):
            return content
    return content


def fetch(
    source: str,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    ttl: TtlPolicy,
    kind: str = "json",
    not_found: frozenset[int] = frozenset(),
    ttl_for: Callable[[Any, int], int] | None = None,
    client: httpx.Client | None = None,
) -> Fetched:
    """Fetch and decode one upstream document, serving it from cache when fresh.

    ``kind`` is ``"json"`` or ``"text"``. A status listed in ``not_found`` yields a
    ``None`` payload (cached briefly) instead of an error. ``ttl_for`` may
    refine the lifetime from the decoded payload, for example to cache a
    finished event for longer than a scheduled one.
    """
    key = json.dumps([source, base_url(source), path, sorted((params or {}).items()), kind])
    cached = _cache.get(key)
    if cached is not None:
        return cached

    accept = "application/json" if kind == "json" else "text/html,application/xhtml+xml"
    deadline = time.monotonic() + QUERY_TIMEOUT
    with _client(client) as http:
        response = _request(source, path, params, accept=accept, client=http, deadline=deadline)

    if response.status_code in not_found:
        result = Fetched(payload=None, ttl=min(ttl.default, 300), status=response.status_code)
        _cache.store(key, result)
        return result
    if not response.is_success:
        raise UpstreamError(source, response.status_code, _body_bytes(response).decode("utf-8", "replace"))

    body = _body_bytes(response)
    if kind == "json":
        try:
            payload: Any = json.loads(body)
        except ValueError as error:
            raise ValueError(f"{SOURCE_LABELS[source]} returned a non-JSON body for {path}") from error
    else:
        payload = body.decode(response.encoding or "utf-8", "replace")

    lifetime = ttl.resolve(_max_age(response))
    if ttl_for is not None:
        lifetime = ttl_for(payload, lifetime)
    result = Fetched(payload=payload, ttl=lifetime, status=response.status_code)
    _cache.store(key, result)
    return result


# --- Resource-specific helpers ------------------------------------------------

#: The UFC feed sends no Cache-Control. Scheduled or live cards change often,
#: while a final card is effectively immutable.
FEED_TTL = TtlPolicy(default=60, minimum=30, maximum=21_600)
FEED_FINAL_TTL = 21_600
ESPN_SCOREBOARD_TTL = TtlPolicy(default=300, minimum=120, maximum=1_800)
ESPN_DETAIL_TTL = TtlPolicy(default=600, minimum=120, maximum=3_600)
RANKINGS_TTL = TtlPolicy(default=3_600, minimum=300, maximum=3_600)
#: ESPN answers an unknown event with 404 and an unknown athlete with 400.
ESPN_NOT_FOUND = frozenset({400, 404})


def _feed_ttl(payload: Any, lifetime: int) -> int:
    if isinstance(payload, dict):
        detail = payload.get("LiveEventDetail") or payload.get("LiveFightDetail")
        if isinstance(detail, dict) and detail.get("Status") == "Final":
            return FEED_FINAL_TTL
    return lifetime


def fetch_feed_event(event_id: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch one UFC live-data event document (``{"LiveEventDetail": {...}}``)."""
    if event_id <= 0:
        raise ValueError("event_id must be positive")
    result = fetch("ufc_feed", f"event/live/{event_id}.json", ttl=FEED_TTL, ttl_for=_feed_ttl, client=client)
    if not isinstance(result.payload, dict) or not isinstance(result.payload.get("LiveEventDetail"), dict):
        raise ValueError("UFC live-data event response has no LiveEventDetail object")
    return result


def fetch_feed_events(event_ids: Sequence[int]) -> list[Fetched]:
    """Fetch several UFC feed events over one connection pool, a few at a time."""
    with (
        httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client,
        ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool,
    ):
        return list(pool.map(lambda event_id: fetch_feed_event(event_id, client=client), event_ids))


def fetch_feed_fight(fight_id: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch one UFC live-data fight document (``{"LiveFightDetail": {...}}``)."""
    if fight_id <= 0:
        raise ValueError("fight_id must be positive")
    result = fetch("ufc_feed", f"fight/live/{fight_id}.json", ttl=FEED_TTL, ttl_for=_feed_ttl, client=client)
    if not isinstance(result.payload, dict) or not isinstance(result.payload.get("LiveFightDetail"), dict):
        raise ValueError("UFC live-data fight response has no LiveFightDetail object")
    return result


def fetch_scoreboard(league: str, season: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch one league's ESPN scoreboard for a calendar year."""
    result = fetch(
        "espn_site",
        f"{league}/scoreboard",
        {"dates": season, "limit": 1000},
        ttl=ESPN_SCOREBOARD_TTL,
        client=client,
    )
    if not isinstance(result.payload, dict) or not isinstance(result.payload.get("events"), list):
        raise ValueError("ESPN scoreboard response has no events array")
    return result


def fetch_fightcenter(league: str, event_id: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch an ESPN fightcenter event (cards, bouts, results). an unknown id yields ``None``."""
    if event_id <= 0:
        raise ValueError("event_id must be positive")
    return fetch(
        "espn_common",
        f"{league}/fightcenter/{event_id}",
        ttl=ESPN_DETAIL_TTL,
        not_found=ESPN_NOT_FOUND,
        client=client,
    )


def fetch_athlete(fighter_id: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch an ESPN MMA athlete profile with fight history. an unknown id yields ``None``."""
    if fighter_id <= 0:
        raise ValueError("fighter_id must be positive")
    return fetch(
        "espn_common", f"athletes/{fighter_id}", ttl=ESPN_DETAIL_TTL, not_found=ESPN_NOT_FOUND, client=client
    )


def fetch_athlete_stats(fighter_id: int, *, client: httpx.Client | None = None) -> Fetched:
    """Fetch an ESPN MMA athlete's per-fight statistics. an unknown id yields ``None``."""
    if fighter_id <= 0:
        raise ValueError("fighter_id must be positive")
    return fetch(
        "espn_common",
        f"athletes/{fighter_id}/stats",
        ttl=ESPN_DETAIL_TTL,
        not_found=ESPN_NOT_FOUND,
        client=client,
    )


def fetch_rankings_html(*, client: httpx.Client | None = None) -> Fetched:
    """Fetch the official ufc.com rankings page as HTML text."""
    return fetch("ufc_web", "rankings", ttl=RANKINGS_TTL, kind="text", client=client)
