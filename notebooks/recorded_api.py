"""Serve one exact public fight response, or one bounded live read; no fallback."""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen


class RecordedAPI:
    """Use the worker's supported endpoint seam with a strict one-read budget."""

    def __init__(self, directory: Path, mode: str, artifact_dir: Path):
        if mode not in {"replay", "live"}:
            raise ValueError("Expected replay or live")
        entry = json.loads((directory / "manifest.json").read_text())["responses"][0]
        body = (directory / entry["file"]).read_bytes()
        if len(body) != entry["bytes"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("Recording hash or size mismatch")
        if entry["url"] != "https://d29dxerjsp82wz.cloudfront.net/api/v3/fight/live/12000.json":
            raise ValueError("Unexpected upstream")
        artifact_dir.mkdir(exist_ok=True)
        self.requests = []
        self.lock = threading.Lock()
        owner = self
        audit_file = artifact_dir / "request-audit.json"
        audit_file.write_text("[]\n")

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_GET(self):
                record = {"path": self.path, "started_utc": datetime.now(UTC).isoformat()}
                with owner.lock:
                    owner.requests.append(record)
                    ordinal = len(owner.requests)
                try:
                    if self.path != "/fight/live/12000.json" or ordinal > 1:
                        raise ValueError("Outside one-fight/one-read budget")
                    served = body
                    if mode == "live":
                        request = Request(
                            entry["url"],
                            headers={
                                "User-Agent": "vgi-ufc-notebooks/1.0 (+https://github.com/Query-farm/vgi-ufc)"
                            },
                        )
                        with urlopen(request, timeout=30) as response:
                            served = response.read(4_000_001)
                        if len(served) > 4_000_000:
                            raise ValueError("Response exceeds four-megabyte budget")
                    detail = json.loads(served)["LiveFightDetail"]
                    if detail.get("FightId") != 12000 or detail.get("Status") != "Final":
                        raise ValueError("Expected completed fight 12000")
                    record.update(
                        status=200,
                        bytes=len(served),
                        sha256=hashlib.sha256(served).hexdigest(),
                        received_utc=datetime.now(UTC).isoformat(),
                    )
                    (artifact_dir / "fight-12000.json").write_bytes(served)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "max-age=21600")
                    self.send_header("Content-Length", str(len(served)))
                    self.end_headers()
                    self.wfile.write(served)
                except Exception as exc:
                    record.update(status=400, error=str(exc))
                    self.send_error(400, str(exc))
                finally:
                    with owner.lock:
                        staged = audit_file.with_suffix(".tmp")
                        staged.write_text(json.dumps(owner.requests, indent=2))
                        staged.replace(audit_file)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        """Stop only this notebook's local server."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
