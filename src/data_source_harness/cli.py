"""Command-line entry point for contracts and Phase-0 gates."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .contracts import run_phase0_gate, validate_contract_fixtures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-contracts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate all positive and negative contract fixtures")
    gate = commands.add_parser("phase0-gate", help="run the machine-readable Phase-0 gate")
    gate.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        checks = validate_contract_fixtures()
        payload = {
            "passed": all(check.passed for check in checks),
            "checks": [check.__dict__ for check in checks],
        }
    else:
        report = run_phase0_gate()
        payload = report.to_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if getattr(args, "output", None):
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
