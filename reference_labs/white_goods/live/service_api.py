"""Small contract-backed HTTP service used only by the local reference lab."""

from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def appointment_page(
    appointments: list[dict[str, Any]],
    *,
    service_order_id: str | None,
    cursor: str | None,
    page_size: int,
) -> dict[str, Any]:
    filtered = [
        item
        for item in appointments
        if service_order_id is None or item["service_order_id"] == service_order_id
    ]
    try:
        offset = int(cursor or "0")
    except ValueError as exc:
        raise ValueError("cursor must be a non-negative integer") from exc
    if offset < 0:
        raise ValueError("cursor must be a non-negative integer")
    items = filtered[offset : offset + page_size]
    next_offset = offset + len(items)
    return {
        "items": items,
        "nextCursor": str(next_offset) if next_offset < len(filtered) else None,
    }


class ServiceApiHandler(BaseHTTPRequestHandler):
    appointments: list[dict[str, Any]] = []
    page_size: int = 2
    credential: str = ""

    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if parsed.path != "/v1/appointments":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not-found"})
            return
        if self.headers.get("Authorization") != f"Bearer {self.credential}":
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        query = parse_qs(parsed.query)
        try:
            page = appointment_page(
                self.appointments,
                service_order_id=query.get("serviceOrderId", [None])[0],
                cursor=query.get("cursor", [None])[0],
                page_size=self.page_size,
            )
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, page)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="white-goods-service-api")
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args(argv)
    fixture_path = Path(os.environ["SERVICE_API_FIXTURES"])
    credential_path = Path(os.environ["SERVICE_API_CREDENTIAL_FILE"])
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    ServiceApiHandler.appointments = fixture["appointments"]
    ServiceApiHandler.page_size = fixture["pagination"]["defaultPageSize"]
    ServiceApiHandler.credential = credential_path.read_text(encoding="utf-8").strip()
    server = ThreadingHTTPServer((args.bind, args.port), ServiceApiHandler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
