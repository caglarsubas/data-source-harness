from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from data_source_harness.actions import (
    ActionApproval,
    ActionAuditLedger,
    ActionExecutionFailed,
    ActionGateway,
    ActionRisk,
    ActionSagaCoordinator,
    ActionSagaStep,
    ActionState,
    ApprovalMode,
    ApprovalRequired,
    CompensationSpec,
    HmacApprovalAuthority,
    IdempotencyConflict,
    PreviewMismatch,
    SagaState,
    SourceActionPlan,
)
from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    ConnectorRegistry,
    ConsistencyProfile,
    DataModel,
    RuntimeMode,
)
from data_source_harness.policy import AuthorizationRequest, PolicyDecision, RequestIdentity
from data_source_harness.telemetry import MemoryTelemetrySink

NOW = datetime(2026, 8, 27, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = HmacApprovalAuthority("adlc-test", "data-source-harness", b"test-approval-key-material")


class MutableConnector:
    def __init__(self) -> None:
        self.profile = ConnectorProfile(
            "lab.mutable",
            "1.0.0",
            "harness.connector/v1",
            RuntimeMode.PROCESS,
            frozenset({DataModel.TABULAR}),
            frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.MUTATE}),
            frozenset({"credential-reference"}),
            ConsistencyProfile(supports_version_precondition=True, supports_idempotency_key=True),
            ConnectorLimits(),
        )
        self.status = "scheduled"
        self.version = 1
        self.mutation_count = 0

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        expected = int(request["preconditions"]["version"])
        if expected != self.version:
            return {
                "success": False,
                "postconditions_met": False,
                "source_version": str(self.version),
            }
        self.status = str(request["parameters"]["status"])
        self.version += 1
        self.mutation_count += 1
        return {
            "success": True,
            "postconditions_met": self.status == request["parameters"]["status"],
            "source_version": str(self.version),
        }

    async def discover(self, cursor: str | None = None) -> tuple[Any, ...]:
        return ()

    async def describe(self, asset: Any) -> Any:
        raise NotImplementedError

    def execute(self, request: Any) -> AsyncIterator[Any]:
        raise NotImplementedError


class AgentPolicy:
    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        allowed = (
            request.identity.agent_id == "agent.allowed"
            and request.source_id == "lab.mutable"
            and request.capability is Capability.MUTATE
        )
        return PolicyDecision(
            allowed,
            f"action-policy:{request.identity.request_id}:{request.attributes['stage']}",
            "action_allowed" if allowed else "action_denied",
        )


class ExplodingConnector(MutableConnector):
    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise OSError("synthetic connector outage")


class FailingTelemetrySink:
    async def emit(self, event: Any) -> None:
        raise OSError("synthetic telemetry outage")


def identity(agent_id: str = "agent.allowed") -> RequestIdentity:
    return RequestIdentity("org", "solution", agent_id, "request-1", "trace-1", "policy:v1")


def action(*, action_id: str = "act-1", key: str = "key-1", version: int = 1) -> SourceActionPlan:
    return SourceActionPlan(
        action_id,
        "lab.mutable",
        "appointments",
        "update-status",
        {"status": "completed"},
        {"version": version},
        key,
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "close completed appointment",
        CompensationSpec("restore-status", {"status": "scheduled"}, {"version": 2}),
    )


def approval(plan: SourceActionPlan, *, compensate: bool = True) -> ActionApproval:
    return AUTHORITY.issue(
        action_digest=plan.digest,
        approver_id="human:service-manager",
        policy_digest="policy:v1",
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        allow_compensation=compensate,
        identity=identity(),
        nonce=f"approval:{plan.action_id}:{compensate}",
    )


def gateway() -> tuple[ActionGateway, MutableConnector, MemoryTelemetrySink]:
    connector = MutableConnector()
    registry = ConnectorRegistry()
    registry.register(connector)
    telemetry = MemoryTelemetrySink()
    return (
        ActionGateway(
            registry,
            AgentPolicy(),
            telemetry,
            now=lambda: NOW,
            approval_verifier=AUTHORITY,
        ),
        connector,
        telemetry,
    )


@pytest.mark.asyncio
async def test_preview_approval_idempotency_and_compensation() -> None:
    subject, connector, telemetry = gateway()
    plan = action()
    preview = await subject.preview(plan, identity())
    assert preview.allowed and preview.approval_required
    with pytest.raises(ApprovalRequired):
        await subject.execute(plan, preview, identity())

    receipt = await subject.execute(plan, preview, identity(), approval(plan))
    replay = await subject.execute(plan, preview, identity(), approval(plan))
    assert receipt.state is ActionState.EXECUTED
    assert replay.state is ActionState.ALREADY_EXECUTED
    assert connector.status == "completed" and connector.mutation_count == 1

    compensated = await subject.compensate(plan, receipt, identity(), approval(plan))
    assert compensated.state is ActionState.COMPENSATED
    assert compensated.compensation_of == receipt.receipt_id
    assert connector.status == "scheduled" and connector.mutation_count == 2
    assert subject.audit.verify()
    assert all("status" not in event.attributes for event in telemetry.events)


@pytest.mark.asyncio
async def test_human_prefix_without_authority_signature_cannot_approve() -> None:
    subject, _, _ = gateway()
    plan = action()
    preview = await subject.preview(plan, identity())
    forged = ActionApproval(
        "forged",
        plan.digest,
        "human:service-manager",
        "policy:v1",
        NOW - timedelta(minutes=1),
        NOW + timedelta(minutes=10),
        True,
    )
    with pytest.raises(ApprovalRequired, match="untrusted"):
        await subject.execute(plan, preview, identity(), forged)


@pytest.mark.asyncio
async def test_signed_approval_is_bound_to_request_identity() -> None:
    subject, _, _ = gateway()
    plan = action()
    other_identity = RequestIdentity(
        "org", "solution", "agent.allowed", "request-2", "trace-2", "policy:v1"
    )
    preview = await subject.preview(plan, other_identity)
    with pytest.raises(ApprovalRequired, match="untrusted"):
        await subject.execute(plan, preview, other_identity, approval(plan))


@pytest.mark.asyncio
async def test_denial_precondition_failure_and_idempotency_collision_fail_closed() -> None:
    subject, connector, _ = gateway()
    denied_preview = await subject.preview(action(), identity("agent.denied"))
    assert not denied_preview.allowed
    with pytest.raises(PreviewMismatch):
        await subject.execute(
            action(), denied_preview, identity("agent.denied"), approval(action())
        )

    stale = action(action_id="stale", key="stale", version=99)
    stale_preview = await subject.preview(stale, identity())
    with pytest.raises(ActionExecutionFailed) as failed:
        await subject.execute(stale, stale_preview, identity(), approval(stale))
    assert failed.value.receipt.state is ActionState.FAILED
    assert connector.mutation_count == 0

    first = action()
    first_preview = await subject.preview(first, identity())
    await subject.execute(first, first_preview, identity(), approval(first))
    collision = action(action_id="other", key="key-1", version=2)
    collision_preview = await subject.preview(collision, identity())
    with pytest.raises(IdempotencyConflict):
        await subject.execute(collision, collision_preview, identity(), approval(collision))
    assert connector.mutation_count == 1


@pytest.mark.asyncio
async def test_expired_preview_and_compensation_scope_are_rejected() -> None:
    clock = [NOW]
    connector = MutableConnector()
    registry = ConnectorRegistry()
    registry.register(connector)
    subject = ActionGateway(
        registry,
        AgentPolicy(),
        MemoryTelemetrySink(),
        now=lambda: clock[0],
        approval_verifier=AUTHORITY,
    )
    plan = action()
    preview = await subject.preview(plan, identity(), ttl=timedelta(seconds=1))
    clock[0] += timedelta(seconds=2)
    with pytest.raises(PreviewMismatch):
        await subject.execute(plan, preview, identity(), approval(plan))

    clock[0] = NOW
    preview = await subject.preview(plan, identity())
    receipt = await subject.execute(plan, preview, identity(), approval(plan))
    with pytest.raises(ApprovalRequired):
        await subject.compensate(plan, receipt, identity(), approval(plan, compensate=False))


@pytest.mark.asyncio
async def test_saga_compensates_successful_steps_after_later_failure() -> None:
    subject, connector, _ = gateway()
    first = action()
    stale = action(action_id="act-2", key="key-2", version=99)
    outcome = await ActionSagaCoordinator(subject).run(
        (
            ActionSagaStep(first, approval(first)),
            ActionSagaStep(stale, approval(stale)),
        ),
        identity(),
    )
    assert outcome.state is SagaState.COMPENSATED
    assert outcome.failed_action_id == stale.action_id
    assert len(outcome.receipts) == 1
    assert len(outcome.compensation_receipts) == 1
    assert connector.status == "scheduled"
    assert subject.audit.verify()


@pytest.mark.asyncio
async def test_connector_and_telemetry_outages_preserve_safe_action_state() -> None:
    broken = ExplodingConnector()
    registry = ConnectorRegistry()
    registry.register(broken)
    subject = ActionGateway(
        registry,
        AgentPolicy(),
        MemoryTelemetrySink(),
        now=lambda: NOW,
        approval_verifier=AUTHORITY,
    )
    plan = action()
    preview = await subject.preview(plan, identity())
    with pytest.raises(ActionExecutionFailed) as failed:
        await subject.execute(plan, preview, identity(), approval(plan))
    assert failed.value.receipt.state is ActionState.FAILED
    assert subject.audit.verify()

    connector = MutableConnector()
    registry = ConnectorRegistry()
    registry.register(connector)
    subject = ActionGateway(
        registry,
        AgentPolicy(),
        FailingTelemetrySink(),
        now=lambda: NOW,
        approval_verifier=AUTHORITY,
    )
    preview = await subject.preview(plan, identity())
    receipt = await subject.execute(plan, preview, identity(), approval(plan))
    replay = await subject.execute(plan, preview, identity(), approval(plan))
    assert receipt.state is ActionState.EXECUTED
    assert replay.state is ActionState.ALREADY_EXECUTED
    assert connector.mutation_count == 1
    assert any(entry.event_type == "telemetry-failed" for entry in subject.audit.entries)
    assert subject.audit.verify()


def test_action_contract_serializers_validate_and_audit_detects_tampering() -> None:
    plan = action()
    preview = ActionGateway(
        ConnectorRegistry(), AgentPolicy(), MemoryTelemetrySink(), now=lambda: NOW
    )
    plan_schema = json.loads((ROOT / "schemas/v1/source-action-plan.schema.json").read_text())
    jsonschema.Draft202012Validator(plan_schema).validate(plan.to_contract())

    ledger = ActionAuditLedger()
    ledger.append("previewed", "act-1", NOW, {"allowed": True})
    assert ledger.verify()
    ledger._entries[0] = ledger._entries[0].__class__(  # type: ignore[attr-defined]
        **{**ledger._entries[0].__dict__, "event_type": "executed"}  # type: ignore[attr-defined]
    )
    assert not ledger.verify()
    assert preview.audit.verify()
