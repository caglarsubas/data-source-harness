"""Deterministic process worker for production-shape white-goods source contracts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parent


def _response(request_id: str, result: dict[str, Any] | None, error: str | None) -> None:
    document = {
        "protocol": "harness.worker/v1",
        "requestId": request_id,
        "result": result,
        "error": {"code": error} if error else None,
    }
    sys.stdout.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "postgres.query":
        path = LAB_ROOT / "data/service/service_orders.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return {"rows": len(rows), "schema": sorted(rows[0]), "source": "postgresql-shape"}
    if operation == "s3.get":
        name = str(payload.get("name", ""))
        root = (LAB_ROOT / "data/documents").resolve()
        path = (root / name).resolve()
        if not path.is_file() or path.parent != root:
            raise ValueError("document_not_found")
        content = path.read_bytes()
        return {
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "source": "s3-shape",
        }
    if operation == "events.poll":
        path = LAB_ROOT / "data/events/telemetry.jsonl"
        events = [line for line in path.read_text().splitlines() if line]
        return {"events": len(events), "checkpoint": str(len(events)), "source": "kafka-shape"}
    if operation == "rest.get":
        document = json.loads((LAB_ROOT / "data/api/service-api-fixtures.json").read_text())
        return {"records": len(document), "source": "rest-shape"}
    if operation == "runtime.environment":
        sensitive = ("AWS_SECRET_ACCESS_KEY", "DATABASE_PASSWORD", "BEARER_TOKEN")
        return {"sensitiveVariablesPresent": [name for name in sensitive if name in os.environ]}
    raise ValueError("operation_not_supported")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("normal", "slow", "oversize", "crash"), default="normal")
    args = parser.parse_args(argv)
    line = sys.stdin.buffer.readline()
    request: dict[str, Any] = json.loads(line)
    request_id = str(request.get("requestId", "missing"))
    if args.mode == "crash":
        return 17
    if args.mode == "slow":
        time.sleep(0.2)
    if args.mode == "oversize":
        _response(request_id, {"payload": "x" * 16384}, None)
        return 0
    try:
        result = _handle(str(request["operation"]), dict(request["payload"]))
    except (KeyError, TypeError, ValueError) as exc:
        _response(request_id, None, str(exc))
        return 0
    _response(request_id, result, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
