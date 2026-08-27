"""Minimal tenant-local runtime host for health and deployment lifecycle checks."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__


class RuntimeStatusHandler(BaseHTTPRequestHandler):
    server_version = "DataSourceHarness/0.8"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "healthy", "version": __version__})
        elif self.path == "/readyz":
            self._json(HTTPStatus.OK, {"status": "ready", "version": __version__})
        elif self.path == "/version":
            self._json(HTTPStatus.OK, {"version": __version__})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: HTTPStatus, payload: dict[str, str]) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harness-runtime")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    server = ThreadingHTTPServer((args.bind, args.port), RuntimeStatusHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - operator shutdown
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
