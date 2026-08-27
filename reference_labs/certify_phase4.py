"""Machine-readable Phase-4 governed-action and adaptive-semantics certification."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from data_source_harness.delegation import A2AActionDelegationAdapter, DelegationRejected
from data_source_harness.models import LineageRef
from data_source_harness.policy import RequestIdentity
from data_source_harness.semantic import AssertionPredicate, SemanticAssertion
from data_source_harness.semantic_memory import (
    GovernedSemanticMemory,
    MemoryScope,
    SemanticMemoryCandidate,
)
from reference_labs.cold_chain.certify import certify_phase3
from reference_labs.cold_chain.phase4 import incident_action
from reference_labs.cold_chain.phase4 import run_action_scenario as run_cold_chain
from reference_labs.white_goods.certify import CertificationCheck, MetricResult, _metric
from reference_labs.white_goods.phase4 import run_action_scenario as run_white_goods
from reference_labs.white_goods.phase4 import run_saga_scenario, service_action

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GQM_PATH = Path(__file__).resolve().with_name("phase4-gqm-plan.json")
FIXED_TIME = datetime(2026, 8, 27, 11, tzinfo=UTC)


@dataclass(frozen=True)
class Phase4Report:
    phase: str
    labs: tuple[str, ...]
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity(agent: str) -> RequestIdentity:
    return RequestIdentity("org-lab", "shared-lab", agent, "p4-request", "p4-trace", "policy:p4")


def _memory_evidence() -> tuple[bool, bool, str]:
    memory = GovernedSemanticMemory()
    candidate = SemanticMemoryCandidate(
        "phase4-shared-semantic",
        SemanticAssertion(
            "phase4-assertion",
            "field:resolution_state",
            AssertionPredicate.SAME_AS,
            "concept:case-status",
            0.96,
            FIXED_TIME,
            FIXED_TIME,
            None,
            "policy:p4",
            (LineageRef("lab.schema", "cases", "resolution_state"),),
        ),
        "agent.semantic-mapper",
        "sha256:phase4-schema",
        MemoryScope(
            "org-lab",
            "shared-lab",
            frozenset({"agent.semantic-mapper", "agent.case-responder"}),
        ),
    )
    memory.propose(candidate)
    unreviewed_denied = False
    try:
        memory.promote(candidate.candidate_id)
    except PermissionError:
        unreviewed_denied = True
    agent_review_denied = False
    try:
        memory.review(candidate.candidate_id, "agent.self-review", FIXED_TIME, approve=True)
    except PermissionError:
        agent_review_denied = True
    memory.review(candidate.candidate_id, "human:semantic-steward", FIXED_TIME, approve=True)
    promoted = memory.promote(candidate.candidate_id)
    scope_correct = (
        memory.view(_identity("agent.case-responder")) == (promoted,)
        and memory.view(_identity("agent.outsider")) == ()
    )
    return (
        unreviewed_denied and agent_review_denied,
        scope_correct,
        "unreviewed and agent self-review denied; scoped responder allowed",
    )


def _delegation_evidence() -> tuple[bool, int, str]:
    action = service_action()
    identity = RequestIdentity(
        "org-lab",
        "whitegoods-lab",
        "agent.whitegoods-service",
        "delegate-request",
        "delegate-trace",
        "policy:wg-v1",
    )
    adapter = A2AActionDelegationAdapter(frozenset({(action.source_id, action.operation)}))
    envelope = {
        "protocol": "a2a/1.0",
        "taskId": "task-reschedule-1",
        "requestingAgent": identity.agent_id,
        "sourceAction": {
            "actionId": action.action_id,
            "sourceId": action.source_id,
            "assetId": action.asset_id,
            "operation": action.operation,
            "parameters": dict(action.parameters),
            "preconditions": dict(action.preconditions),
            "idempotencyKey": action.idempotency_key,
            "risk": action.risk.value,
            "approvalMode": action.approval_mode.value,
            "purpose": action.purpose,
            "compensation": {
                "operation": action.compensation.operation,
                "parameters": dict(action.compensation.parameters),
                "preconditions": dict(action.compensation.preconditions),
            },
        },
    }
    mapped = adapter.to_action_plan(envelope, identity)
    rejected_overbroad = False
    try:
        adapter.to_action_plan({**envelope, "shell": "forbidden"}, identity)
    except DelegationRejected:
        rejected_overbroad = True
    connector_source = (
        (REPOSITORY_ROOT / "src/data_source_harness/connector.py").read_text().lower()
    )
    coupling_tokens = sum(token in connector_source for token in ("a2a", "mcp"))
    bounded = mapped.digest == action.digest and rejected_overbroad
    return bounded, coupling_tokens, "exact action mapped; over-broad envelope rejected"


def _cross_plane_boundary() -> tuple[bool, str]:
    boundary = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase4-cross-plane-boundary.json").read_text()
    )
    release_set = json.loads(
        (REPOSITORY_ROOT / "compatibility/cross-plane-release-set.lock.json").read_text()
    )
    expected = {item["name"]: item["revision"] for item in release_set["components"]}
    actual = {item["name"]: item["revision"] for item in boundary["components"]}
    model_boundary = next(item for item in boundary["components"] if item["name"] == "model-plane")
    no_sync_model = any(
        "no synchronous dependency" in item for item in model_boundary["harnessBoundary"]
    )
    return (
        expected == actual and no_sync_model,
        f"pins={len(actual)}; no_sync_model={no_sync_model}",
    )


def _action_capabilities() -> tuple[bool, str]:
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/source-action-capability-profile.schema.json").read_text()
    )
    expected = {
        "whitegoods.service-actions": (
            service_action().operation,
            service_action().compensation.operation,
        ),
        "coldchain.incident-actions": (
            incident_action().operation,
            incident_action().compensation.operation,
        ),
    }
    valid = True
    for lab, filename in (
        ("white_goods", "action-capabilities.json"),
        ("cold_chain", "action-capabilities.json"),
    ):
        document = json.loads((REPOSITORY_ROOT / "reference_labs" / lab / filename).read_text())
        if not jsonschema.Draft202012Validator(schema).is_valid(document):
            valid = False
            continue
        operation = document["operations"][0]
        valid = (
            valid
            and (operation["operation"], operation["compensationOperation"])
            == expected[document["sourceId"]]
        )
    return valid, f"profiles={len(expected)}; operations={len(expected)}"


async def certify_phase4() -> Phase4Report:
    phase3 = certify_phase3()
    white_goods, cold_chain, saga_compensated = await asyncio.gather(
        run_white_goods(), run_cold_chain(), run_saga_scenario()
    )
    memory_controlled, memory_scoped, memory_detail = _memory_evidence()
    delegation_bounded, coupling_tokens, delegation_detail = _delegation_evidence()
    boundary_valid, boundary_detail = _cross_plane_boundary()
    capabilities_valid, capabilities_detail = _action_capabilities()
    previews = white_goods.previewed and cold_chain.previewed
    false_allow_rate = 0.0 if white_goods.unauthorized_denied else 1.0
    idempotent = white_goods.idempotent and cold_chain.idempotent
    compensated_and_audited = (
        white_goods.compensated
        and cold_chain.compensated
        and white_goods.audit_valid
        and cold_chain.audit_valid
        and white_goods.payload_free_audit
        and cold_chain.payload_free_audit
    )
    checks = [
        CertificationCheck("regression.phase3", phase3.passed, "Phase-3 certificate rerun"),
        CertificationCheck(
            "actions.two-independent-labs",
            previews and idempotent,
            "white-goods service and cold-chain incident sources",
        ),
        CertificationCheck(
            "actions.authorization-and-approval",
            false_allow_rate == 0 and white_goods.approval_denied,
            (
                f"false_allow_rate={false_allow_rate}; "
                f"missing_approval_denied={white_goods.approval_denied}"
            ),
        ),
        CertificationCheck(
            "actions.conditional-compensation-audit",
            cold_chain.precondition_denied and compensated_and_audited,
            "stale write denied; both actions compensated; audit chains valid and payload-free",
        ),
        CertificationCheck(
            "actions.saga-reverse-compensation",
            saga_compensated,
            "later stale step compensated its successful predecessor",
        ),
        CertificationCheck(
            "semantics.governed-shared-memory",
            memory_controlled and memory_scoped,
            memory_detail,
        ),
        CertificationCheck(
            "delegation.bounded-adapter-isolation",
            delegation_bounded and coupling_tokens == 0,
            f"{delegation_detail}; connector_coupling_tokens={coupling_tokens}",
        ),
        CertificationCheck(
            "compatibility.cross-plane-ownership-boundary",
            boundary_valid,
            boundary_detail,
        ),
        CertificationCheck(
            "actions.capability-profiles",
            capabilities_valid,
            capabilities_detail,
        ),
    ]
    plan = json.loads(GQM_PATH.read_text())
    definitions = {item["metricId"]: item for item in plan["metrics"]}
    metrics = (
        _metric(definitions, "P4-M1", float(previews), "2/2 labs previewed"),
        _metric(
            definitions,
            "P4-M2",
            false_allow_rate,
            "unauthorized agent and unexposed operation",
        ),
        _metric(
            definitions,
            "P4-M3",
            float(white_goods.approval_denied),
            "missing approval blocked before mutation",
        ),
        _metric(definitions, "P4-M4", float(idempotent), "one source effect per key in both labs"),
        _metric(
            definitions,
            "P4-M5",
            float(cold_chain.precondition_denied),
            "stale version/value rejected",
        ),
        _metric(
            definitions,
            "P4-M6",
            float(compensated_and_audited),
            "2/2 compensations; audit chain and payload controls",
        ),
        _metric(definitions, "P4-M7", float(memory_controlled), memory_detail),
        _metric(definitions, "P4-M8", float(memory_scoped), memory_detail),
        _metric(definitions, "P4-M9", float(delegation_bounded), delegation_detail),
        _metric(definitions, "P4-M10", float(coupling_tokens), "connector.py scan"),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase4-plan-complete",
            {item["metricId"] for item in plan["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(plan['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = all(check.passed for check in checks) and all(metric.passed for metric in metrics)
    return Phase4Report(
        "phase-4",
        ("white-goods-service-quality-lab", "cold-chain-excursion-response-lab"),
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies deterministic source-action safety and semantic governance in two "
            "synthetic application labs. It does not prove production connectors, durable "
            "crash recovery, live A2A interoperability, deployment runtime or stakeholder approval."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase4-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase4())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
