"""Command-line entry point for contracts and Phase-0 gates."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import jsonschema

from .acceptance import LiveAcceptanceCampaign
from .contracts import SCHEMA_DIR, load_json, run_phase0_gate, validate_contract_fixtures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness-contracts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="validate all positive and negative contract fixtures")
    gate = commands.add_parser("phase0-gate", help="run the machine-readable Phase-0 gate")
    gate.add_argument("--output", type=Path)
    acceptance = commands.add_parser(
        "verify-acceptance", help="validate and recompute a Phase-7 acceptance campaign"
    )
    acceptance.add_argument("--input", type=Path, required=True)
    acceptance.add_argument("--require-accepted", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        checks = validate_contract_fixtures()
        payload = {
            "passed": all(check.passed for check in checks),
            "checks": [check.__dict__ for check in checks],
        }
    elif args.command == "phase0-gate":
        report = run_phase0_gate()
        payload = report.to_dict()
    else:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        schema = load_json(SCHEMA_DIR / "live-acceptance-campaign.schema.json")
        errors = list(
            jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            ).iter_errors(document)
        )
        try:
            campaign = LiveAcceptanceCampaign.from_contract(document) if not errors else None
            parse_error = ""
        except (KeyError, TypeError, ValueError) as exc:
            campaign = None
            parse_error = str(exc)
        structurally_valid = not errors and campaign is not None
        accepted = campaign.accepted if campaign else False
        payload = {
            "passed": structurally_valid and (accepted or not args.require_accepted),
            "structurallyValid": structurally_valid,
            "accepted": accepted,
            "releaseSetDigest": campaign.release_set_digest if campaign else None,
            "blockers": list(campaign.blockers) if campaign else [],
            "errors": [error.message for error in errors] + ([parse_error] if parse_error else []),
        }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if getattr(args, "output", None):
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
