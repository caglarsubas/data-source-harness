"""Governed incident acknowledgement action scenario for the cold-chain lab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from data_source_harness.actions import (
    ActionApproval,
    ActionExecutionFailed,
    ActionGateway,
    ActionRisk,
    ActionState,
    ApprovalMode,
    CompensationSpec,
    SourceActionPlan,
)
from data_source_harness.connector import ConnectorRegistry
from data_source_harness.policy import RequestIdentity
from data_source_harness.telemetry import MemoryTelemetrySink
from reference_labs.phase4_support import BoundedLabActionPolicy, LabMutationConnector

FIXED_TIME = datetime(2026, 8, 27, 10, tzinfo=UTC)


@dataclass(frozen=True)
class ColdChainActionResult:
    previewed: bool
    precondition_denied: bool
    idempotent: bool
    compensated: bool
    audit_valid: bool
    payload_free_audit: bool


def incident_action(*, expected_version: int = 1) -> SourceActionPlan:
    return SourceActionPlan(
        "coldchain-acknowledge-excursion",
        "coldchain.incident-actions",
        "incidents",
        "acknowledge-excursion",
        {"newValue": "acknowledged"},
        {"expectedVersion": expected_version, "expectedValue": "open"},
        f"cc-incident-0003:ack:{expected_version}",
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "acknowledge verified temperature excursion",
        CompensationSpec(
            "reopen-excursion",
            {"newValue": "open"},
            {"expectedVersion": 2, "expectedValue": "acknowledged"},
        ),
    )


def _identity() -> RequestIdentity:
    return RequestIdentity(
        "org-lab",
        "coldchain-lab",
        "agent.coldchain-responder",
        "cc-request",
        "cc-trace",
        "policy:cc-v1",
    )


def _approval(action: SourceActionPlan) -> ActionApproval:
    return ActionApproval(
        f"cc-approval:{action.action_id}",
        action.digest,
        "human:logistics-supervisor",
        "policy:cc-v1",
        FIXED_TIME - timedelta(minutes=1),
        FIXED_TIME + timedelta(minutes=10),
        True,
    )


async def run_action_scenario() -> ColdChainActionResult:
    connector = LabMutationConnector("coldchain.incident-actions", "incidents", "open")
    registry = ConnectorRegistry()
    registry.register(connector)
    telemetry = MemoryTelemetrySink()
    gateway = ActionGateway(
        registry,
        BoundedLabActionPolicy(
            "coldchain.incident-actions",
            "incidents",
            "agent.coldchain-responder",
            frozenset({"acknowledge-excursion", "reopen-excursion"}),
        ),
        telemetry,
        now=lambda: FIXED_TIME,
    )
    stale = incident_action(expected_version=99)
    stale_preview = await gateway.preview(stale, _identity())
    precondition_denied = False
    try:
        await gateway.execute(stale, stale_preview, _identity(), _approval(stale))
    except ActionExecutionFailed:
        precondition_denied = True
    action = incident_action()
    preview = await gateway.preview(action, _identity())
    receipt = await gateway.execute(action, preview, _identity(), _approval(action))
    replay = await gateway.execute(action, preview, _identity(), _approval(action))
    idempotent = (
        receipt.state is ActionState.EXECUTED
        and replay.state is ActionState.ALREADY_EXECUTED
        and connector.mutation_count == 1
    )
    compensation = await gateway.compensate(action, receipt, _identity(), _approval(action))
    compensated = (
        compensation.state is ActionState.COMPENSATED
        and connector.value == "open"
        and connector.mutation_count == 2
    )
    sensitive_values = {"open", "acknowledged"}
    payload_free = all(
        not sensitive_values.intersection(str(value) for value in entry.attributes.values())
        for entry in gateway.audit.entries
    )
    return ColdChainActionResult(
        preview.allowed,
        precondition_denied,
        idempotent,
        compensated,
        gateway.audit.verify(),
        payload_free,
    )
