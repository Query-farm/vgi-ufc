"""Serve the recorded upstream fixtures over HTTP for the SQL tests.

``ci/run-integration.sh`` starts this server, points the worker's base-URL
environment variables at it, and runs ``test/sql`` through DuckDB, so the
suite is hermetic. Prints ``PORT:<n>`` once listening.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from fixture_server import serve_fixtures  # noqa: E402


def main() -> None:
    """Serve until killed."""
    with serve_fixtures() as overrides:
        print(f"PORT:{urlparse(overrides['UFC_FEED_BASE_URL']).port}", flush=True)
        threading.Event().wait()


if __name__ == "__main__":
    main()
