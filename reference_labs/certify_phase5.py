"""Machine-readable Phase-5 durable recovery and protocol-edge certification."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import jsonschema

from data_source_harness.policy import RequestIdentity
from data_source_harness.protocol import (
    PROTOCOL_VERSION,
    NorthboundActionAdapter,
    NorthboundTool,
    NorthboundToolCatalog,
)
from reference_labs.cold_chain.phase4 import incident_action
from reference_labs.cold_chain.phase5 import run_recovery_scenario as run_cold_chain
from reference_labs.white_goods.certify import (
    CertificationCheck,
    MetricResult,
    _metric,
    deny_network,
)
from reference_labs.white_goods.phase4 import service_action
from reference_labs.white_goods.phase5 import run_recovery_scenario as run_white_goods

from .certify_phase4 import certify_phase4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GQM_PATH = Path(__file__).resolve().with_name("phase5-gqm-plan.json")


@dataclass(frozen=True)
class Phase5Report:
    phase: str
    labs: tuple[str, ...]
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity(agent: str) -> RequestIdentity:
    return RequestIdentity("org-lab", "shared-lab", agent, "p5-request", "p5-trace", "policy:p5")


def _tool(name: str, action: Any, agent: str) -> NorthboundTool:
    return NorthboundTool(
        name,
        f"Bounded tool for {action.operation}",
        action.source_id,
        action.asset_id,
        action.operation,
        action.risk,
        action.approval_mode,
        action.purpose,
        frozenset({agent}),
    )


def _call(catalog: NorthboundToolCatalog, action: Any) -> dict[str, Any]:
    compensation = None
    if action.compensation:
        compensation = {
            "operation": action.compensation.operation,
            "parameters": dict(action.compensation.parameters),
            "preconditions": dict(action.compensation.preconditions),
        }
    return {
        "jsonrpc": "2.0",
        "id": "p5-call",
        "method": "tools/call",
        "protocolVersion": PROTOCOL_VERSION,
        "catalogDigest": catalog.digest,
        "params": {
            "name": "whitegoods.reschedule",
            "arguments": {
                "actionId": action.action_id,
                "parameters": dict(action.parameters),
                "preconditions": dict(action.preconditions),
                "idempotencyKey": action.idempotency_key,
                "compensation": compensation,
            },
        },
    }


def _protocol_evidence() -> tuple[bool, bool, bool, int, str]:
    white_goods = service_action()
    cold_chain = incident_action()
    catalog = NorthboundToolCatalog(
        (
            _tool("whitegoods.reschedule", white_goods, "agent.whitegoods-service"),
            _tool("coldchain.acknowledge", cold_chain, "agent.coldchain-responder"),
        )
    )
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/northbound-tool-catalog.schema.json").read_text()
    )
    contract_valid = jsonschema.Draft202012Validator(schema).is_valid(catalog.to_contract())
    adapter = NorthboundActionAdapter(catalog)
    list_request = {
        "jsonrpc": "2.0",
        "id": "p5-list",
        "method": "tools/list",
        "protocolVersion": PROTOCOL_VERSION,
    }
    scoped = adapter.handle(list_request, _identity("agent.whitegoods-service"))
    outsider = adapter.handle(list_request, _identity("agent.outsider"))
    exposed = scoped["result"]["tools"]
    scope_correct = (
        [item["name"] for item in exposed] == ["whitegoods.reschedule"]
        and outsider["result"]["tools"] == []
        and "allowedAgents" not in exposed[0]
    )
    mapped = adapter.to_action_plan(
        _call(catalog, white_goods), _identity("agent.whitegoods-service")
    )
    exact_mapping = mapped.digest == white_goods.digest
    poisoned = replace(catalog.tools[0], description="Changed after client pin")
    changed_catalog = NorthboundToolCatalog((poisoned, catalog.tools[1]))
    stale_response = NorthboundActionAdapter(changed_catalog).handle(
        _call(catalog, white_goods), _identity("agent.whitegoods-service")
    )
    stale_rejected = stale_response.get("error", {}).get("code") == -32010
    connector_source = (
        (REPOSITORY_ROOT / "src/data_source_harness/connector.py").read_text().lower()
    )
    coupling = sum(token in connector_source for token in ("jsonrpc", "northbound", "tools/call"))
    return (
        contract_valid and exact_mapping,
        scope_correct,
        stale_rejected,
        coupling,
        f"catalog={catalog.digest}; tools={len(catalog.tools)}",
    )


async def certify_phase5() -> Phase5Report:
    with deny_network() as network_attempts:
        phase4, white_goods, cold_chain = await asyncio.gather(
            certify_phase4(), run_white_goods(), run_cold_chain()
        )
        protocol_valid, scope_correct, stale_rejected, coupling, protocol_detail = (
            _protocol_evidence()
        )
    labs = (white_goods, cold_chain)
    recovered = all(result.recovered and result.restart_persisted for result in labs)
    blind_replay_rate = sum(not result.blind_replay_blocked for result in labs) / len(labs)
    duplicate_rate = sum(not result.one_source_effect for result in labs) / len(labs)
    unresolved = sum(not result.recovered for result in labs)
    journal_valid = all(result.journal_valid for result in labs)
    payload_exposure = sum(not result.payload_free_journal for result in labs) / len(labs)
    checks = [
        CertificationCheck("regression.phase4", phase4.passed, "Phase-4 certificate rerun"),
        CertificationCheck(
            "durability.two-lab-restart-recovery",
            recovered and all(result.outcome_unknown for result in labs),
            "2/2 injected post-dispatch crash windows reconciled after journal reopen",
        ),
        CertificationCheck(
            "durability.no-blind-replay-or-duplicate",
            blind_replay_rate == 0 and duplicate_rate == 0,
            f"blind_replay_rate={blind_replay_rate}; duplicate_rate={duplicate_rate}",
        ),
        CertificationCheck(
            "durability.journal-integrity-and-privacy",
            journal_valid and payload_exposure == 0,
            "SQLite FULL sync/WAL metadata journal; SHA-256 chain valid; raw values absent",
        ),
        CertificationCheck(
            "protocol.bounded-pinned-catalog",
            protocol_valid and scope_correct and stale_rejected and coupling == 0,
            f"{protocol_detail}; connector_coupling_tokens={coupling}",
        ),
        CertificationCheck(
            "deployment.zero-egress",
            not network_attempts,
            f"blocked-network-attempts={len(network_attempts)}",
        ),
    ]
    plan = json.loads(GQM_PATH.read_text())
    definitions = {item["metricId"]: item for item in plan["metrics"]}
    metrics = (
        _metric(definitions, "P5-M1", float(recovered), "2/2 labs recovered"),
        _metric(definitions, "P5-M2", blind_replay_rate, "2/2 uncertain replays blocked"),
        _metric(definitions, "P5-M3", duplicate_rate, "one source effect per lab"),
        _metric(definitions, "P5-M4", float(unresolved), "no pending action after reconcile"),
        _metric(definitions, "P5-M5", float(journal_valid), "2/2 journal chains valid"),
        _metric(definitions, "P5-M6", payload_exposure, "raw mutation values absent"),
        _metric(definitions, "P5-M7", float(scope_correct), "agent-scoped tools/list"),
        _metric(definitions, "P5-M8", float(not stale_rejected), "changed description denied"),
        _metric(definitions, "P5-M9", float(coupling), "connector.py token scan"),
        _metric(definitions, "P5-M10", float(len(network_attempts)), "socket connect denied"),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase5-plan-complete",
            {item["metricId"] for item in plan["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(plan['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = all(check.passed for check in checks) and all(metric.passed for metric in metrics)
    return Phase5Report(
        "phase-5",
        ("white-goods-service-quality-lab", "cold-chain-excursion-response-lab"),
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies deterministic SQLite write-ahead recovery, source idempotency "
            "reconciliation and a pinned connector-neutral JSON-RPC action boundary in two "
            "synthetic labs with network denied. It does not prove OS power-loss behavior, "
            "production database HA, official MCP/A2A conformance, live OpenShift runtime or "
            "stakeholder acceptance."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase5-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase5())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
