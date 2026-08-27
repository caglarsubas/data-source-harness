"""Governed service-appointment action scenario for the white-goods lab."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from data_source_harness.actions import (
    ActionApproval,
    ActionGateway,
    ActionRisk,
    ActionSagaCoordinator,
    ActionSagaStep,
    ActionState,
    ApprovalMode,
    ApprovalRequired,
    CompensationSpec,
    HmacApprovalAuthority,
    PreviewMismatch,
    SagaState,
    SourceActionPlan,
)
from data_source_harness.connector import ConnectorRegistry
from data_source_harness.policy import RequestIdentity
from data_source_harness.telemetry import MemoryTelemetrySink
from reference_labs.phase4_support import BoundedLabActionPolicy, LabMutationConnector

FIXED_TIME = datetime(2026, 8, 27, 9, tzinfo=UTC)
APPROVAL_AUTHORITY = HmacApprovalAuthority(
    "adlc-whitegoods-lab",
    "data-source-harness",
    b"whitegoods-lab-approval-key-material",
)


@dataclass(frozen=True)
class WhiteGoodsActionResult:
    previewed: bool
    unauthorized_denied: bool
    approval_denied: bool
    idempotent: bool
    compensated: bool
    audit_valid: bool
    payload_free_audit: bool


def service_action() -> SourceActionPlan:
    return SourceActionPlan(
        "whitegoods-reschedule-appointment",
        "whitegoods.service-actions",
        "service_appointments",
        "reschedule-appointment",
        {"newValue": "2026-09-02T09:00:00Z"},
        {"expectedVersion": 1, "expectedValue": "2026-09-01T09:00:00Z"},
        "wg-appointment-1001:reschedule",
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "customer-confirmed service reschedule",
        CompensationSpec(
            "restore-appointment",
            {"newValue": "2026-09-01T09:00:00Z"},
            {"expectedVersion": 2, "expectedValue": "2026-09-02T09:00:00Z"},
        ),
    )


def _identity(agent: str = "agent.whitegoods-service") -> RequestIdentity:
    return RequestIdentity(
        "org-lab", "whitegoods-lab", agent, "wg-request", "wg-trace", "policy:wg-v1"
    )


def _approval(action: SourceActionPlan) -> ActionApproval:
    return APPROVAL_AUTHORITY.issue(
        action_digest=action.digest,
        approver_id="human:service-supervisor",
        policy_digest="policy:wg-v1",
        approved_at=FIXED_TIME - timedelta(minutes=1),
        expires_at=FIXED_TIME + timedelta(minutes=10),
        allow_compensation=True,
        identity=_identity(),
        nonce=f"wg:{action.action_id}",
    )


async def run_action_scenario() -> WhiteGoodsActionResult:
    connector = LabMutationConnector(
        "whitegoods.service-actions",
        "service_appointments",
        "2026-09-01T09:00:00Z",
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    telemetry = MemoryTelemetrySink()
    gateway = ActionGateway(
        registry,
        BoundedLabActionPolicy(
            "whitegoods.service-actions",
            "service_appointments",
            "agent.whitegoods-service",
            frozenset({"reschedule-appointment", "restore-appointment"}),
        ),
        telemetry,
        now=lambda: FIXED_TIME,
        approval_verifier=APPROVAL_AUTHORITY,
    )
    action = service_action()
    denied = await gateway.preview(action, _identity("agent.other"))
    unexposed = replace(
        action,
        action_id="whitegoods-unexposed-operation",
        operation="delete-customer",
        idempotency_key="wg-unexposed",
    )
    unexposed_preview = await gateway.preview(unexposed, _identity())
    unauthorized_denied = not denied.allowed and not unexposed_preview.allowed
    try:
        await gateway.execute(action, denied, _identity("agent.other"), _approval(action))
    except PreviewMismatch:
        unauthorized_denied = unauthorized_denied and True
    else:
        unauthorized_denied = False
    preview = await gateway.preview(action, _identity())
    approval_denied = False
    try:
        await gateway.execute(action, preview, _identity())
    except ApprovalRequired:
        approval_denied = True
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
        and connector.value == "2026-09-01T09:00:00Z"
        and connector.mutation_count == 2
    )
    sensitive_values = {"2026-09-01T09:00:00Z", "2026-09-02T09:00:00Z"}
    payload_free = all(
        not sensitive_values.intersection(str(value) for value in entry.attributes.values())
        for entry in gateway.audit.entries
    )
    return WhiteGoodsActionResult(
        preview.allowed,
        unauthorized_denied,
        approval_denied,
        idempotent,
        compensated,
        gateway.audit.verify(),
        payload_free,
    )


async def run_saga_scenario() -> bool:
    connector = LabMutationConnector(
        "whitegoods.service-actions",
        "service_appointments",
        "2026-09-01T09:00:00Z",
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    gateway = ActionGateway(
        registry,
        BoundedLabActionPolicy(
            "whitegoods.service-actions",
            "service_appointments",
            "agent.whitegoods-service",
            frozenset({"reschedule-appointment", "restore-appointment"}),
        ),
        MemoryTelemetrySink(),
        now=lambda: FIXED_TIME,
        approval_verifier=APPROVAL_AUTHORITY,
    )
    first = service_action()
    stale_second = replace(
        first,
        action_id="whitegoods-confirm-parts-stale",
        idempotency_key="wg-appointment-1001:confirm-parts",
        preconditions={"expectedVersion": 99, "expectedValue": "2026-09-02T09:00:00Z"},
    )
    outcome = await ActionSagaCoordinator(gateway).run(
        (
            ActionSagaStep(first, _approval(first)),
            ActionSagaStep(stale_second, _approval(stale_second)),
        ),
        _identity(),
    )
    return (
        outcome.state is SagaState.COMPENSATED
        and len(outcome.receipts) == 1
        and len(outcome.compensation_receipts) == 1
        and connector.value == "2026-09-01T09:00:00Z"
        and gateway.audit.verify()
    )
