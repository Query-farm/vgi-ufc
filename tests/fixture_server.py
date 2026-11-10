"""A local HTTP server that serves recorded upstream responses for hermetic tests."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_text(name: str) -> str:
    """Return a fixture file's text."""
    return (FIXTURES / name).read_text()


def fixture_json(name: str) -> object:
    """Return a decoded JSON fixture."""
    return json.loads(fixture_text(name))


_EMPTY_SCOREBOARD = {"leagues": [{"id": "3347", "slug": "pfl", "calendar": []}], "events": []}

_ROUTES: list[tuple[re.Pattern[str], str | dict, int]] = [
    (re.compile(r"^/feed/event/live/1291\.json$"), "ufc_event_1291.json", 200),
    (re.compile(r"^/feed/event/live/1350\.json$"), "ufc_event_1350.json", 200),
    (re.compile(r"^/feed/event/live/\d+\.json$"), {"LiveEventDetail": {}}, 200),
    (re.compile(r"^/feed/fight/live/12000\.json$"), "ufc_fight_12000.json", 200),
    (re.compile(r"^/feed/fight/live/\d+\.json$"), {"LiveFightDetail": {}}, 200),
    (re.compile(r"^/site/ufc/scoreboard$"), "espn_scoreboard_ufc_2026.json", 200),
    (re.compile(r"^/site/(pfl|bellator)/scoreboard$"), _EMPTY_SCOREBOARD, 200),
    (re.compile(r"^/common/ufc/fightcenter/600061268$"), "espn_fightcenter_600061268.json", 200),
    (re.compile(r"^/common/athletes/3022677$"), "espn_athlete_3022677.json", 200),
    (re.compile(r"^/common/athletes/3022677/stats$"), "espn_athlete_3022677_stats.json", 200),
    (re.compile(r"^/common/athletes/\d+(/stats)?$"), {"code": 400, "message": "unknown athlete"}, 400),
    (re.compile(r"^/web/rankings$"), "ufc_rankings.html", 200),
]


class FixtureHandler(BaseHTTPRequestHandler):
    """Serve fixtures by path; record every request path and User-Agent."""

    requests: list[tuple[str, str]] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        type(self).requests.append((path, self.headers.get("User-Agent", "")))
        route = next((entry for entry in _ROUTES if entry[0].match(path)), None)
        if route is None:
            self.send_error(404)
            return
        _, source, status = route
        if isinstance(source, dict):
            body = json.dumps(source).encode()
            content_type = "application/json"
        else:
            body = (FIXTURES / source).read_bytes()
            content_type = "text/html; charset=UTF-8" if source.endswith(".html") else "application/json"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def serve_fixtures() -> Iterator[dict[str, str]]:
    """Run the fixture server; yield the environment overrides pointing at it."""
    FixtureHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    try:
        yield {
            "UFC_FEED_BASE_URL": f"{root}/feed",
            "ESPN_SITE_BASE_URL": f"{root}/site",
            "ESPN_COMMON_BASE_URL": f"{root}/common",
            "UFC_WEB_BASE_URL": f"{root}/web",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
