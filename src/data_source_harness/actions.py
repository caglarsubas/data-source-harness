"""Preview-first, policy-enforced and idempotent source mutation workflows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .connector import Capability, ConnectorRegistry
from .models import Scalar
from .policy import (
    AuthorizationRequest,
    PolicyDecision,
    PolicyDenied,
    PolicyEvaluator,
    RequestIdentity,
)
from .telemetry import TelemetryEvent, TelemetrySink


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value)).hexdigest()}"


class ActionRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalMode(StrEnum):
    NONE = "none"
    HUMAN = "human"


class ActionState(StrEnum):
    EXECUTED = "executed"
    ALREADY_EXECUTED = "already-executed"
    COMPENSATED = "compensated"
    FAILED = "failed"


class SagaState(StrEnum):
    COMPLETED = "completed"
    COMPENSATED = "compensated"
    FAILED = "failed"
    COMPENSATION_FAILED = "compensation-failed"


@dataclass(frozen=True)
class CompensationSpec:
    operation: str
    parameters: Mapping[str, Scalar]
    preconditions: Mapping[str, Scalar]

    def __post_init__(self) -> None:
        if not self.operation or not self.parameters or not self.preconditions:
            raise ValueError("compensation requires operation, parameters and preconditions")


@dataclass(frozen=True)
class SourceActionPlan:
    action_id: str
    source_id: str
    asset_id: str
    operation: str
    parameters: Mapping[str, Scalar]
    preconditions: Mapping[str, Scalar]
    idempotency_key: str
    risk: ActionRisk
    approval_mode: ApprovalMode
    purpose: str
    compensation: CompensationSpec | None = None

    def __post_init__(self) -> None:
        required = (
            self.action_id,
            self.source_id,
            self.asset_id,
            self.operation,
            self.idempotency_key,
            self.purpose,
        )
        if any(not value for value in required) or not self.parameters or not self.preconditions:
            raise ValueError("source actions require identity, parameters and preconditions")
        if self.risk is ActionRisk.HIGH and self.approval_mode is not ApprovalMode.HUMAN:
            raise ValueError("high-risk source actions require human approval")

    @property
    def digest(self) -> str:
        compensation = None
        if self.compensation is not None:
            compensation = {
                "operation": self.compensation.operation,
                "parameters": dict(self.compensation.parameters),
                "preconditions": dict(self.compensation.preconditions),
            }
        return _digest(
            {
                "action_id": self.action_id,
                "source_id": self.source_id,
                "asset_id": self.asset_id,
                "operation": self.operation,
                "parameters": dict(self.parameters),
                "preconditions": dict(self.preconditions),
                "idempotency_key": self.idempotency_key,
                "risk": self.risk.value,
                "approval_mode": self.approval_mode.value,
                "purpose": self.purpose,
                "compensation": compensation,
            }
        )

    def to_contract(self) -> dict[str, Any]:
        compensation = None
        if self.compensation is not None:
            compensation = {
                "operation": self.compensation.operation,
                "parametersDigest": _digest(dict(self.compensation.parameters)),
                "preconditionsDigest": _digest(dict(self.compensation.preconditions)),
                "preconditionFields": sorted(self.compensation.preconditions),
            }
        return {
            "schemaVersion": "data.harness/v1",
            "actionId": self.action_id,
            "sourceId": self.source_id,
            "assetId": self.asset_id,
            "operation": self.operation,
            "parametersDigest": _digest(dict(self.parameters)),
            "preconditionsDigest": _digest(dict(self.preconditions)),
            "preconditionFields": sorted(self.preconditions),
            "idempotencyKey": self.idempotency_key,
            "risk": self.risk.value,
            "approvalMode": self.approval_mode.value,
            "purpose": self.purpose,
            "compensation": compensation,
        }


@dataclass(frozen=True)
class ActionPreview:
    preview_id: str
    action_id: str
    action_digest: str
    policy_digest: str
    policy_decision_id: str
    created_at: datetime
    expires_at: datetime
    allowed: bool
    approval_required: bool
    effects: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("preview timestamps must be timezone-aware")
        if self.expires_at <= self.created_at or not self.effects:
            raise ValueError("preview must be time-bounded and expose effects")

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "previewId": self.preview_id,
            "actionId": self.action_id,
            "actionDigest": self.action_digest,
            "policyDigest": self.policy_digest,
            "policyDecisionId": self.policy_decision_id,
            "createdAt": self.created_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "allowed": self.allowed,
            "approvalRequired": self.approval_required,
            "effects": list(self.effects),
        }


@dataclass(frozen=True)
class ActionApproval:
    approval_id: str
    action_digest: str
    approver_id: str
    policy_digest: str
    approved_at: datetime
    expires_at: datetime
    allow_compensation: bool

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.approval_id,
                self.action_digest,
                self.approver_id,
                self.policy_digest,
            )
        ):
            raise ValueError("approval identity, action and policy binding are required")
        if not self.approver_id.startswith("human:"):
            raise ValueError("source action approvals require a human approver")
        if self.approved_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("approval timestamps must be timezone-aware")
        if self.expires_at <= self.approved_at:
            raise ValueError("approval must expire after it is granted")


@dataclass(frozen=True)
class AuditEntry:
    sequence: int
    event_type: str
    action_id: str
    occurred_at: datetime
    attributes: Mapping[str, Scalar]
    previous_digest: str
    digest: str


class ActionAuditLedger:
    """Append-only hash chain that records metadata, never raw mutation parameters."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(
        self,
        event_type: str,
        action_id: str,
        occurred_at: datetime,
        attributes: Mapping[str, Scalar],
    ) -> AuditEntry:
        if occurred_at.tzinfo is None:
            raise ValueError("audit timestamps must be timezone-aware")
        previous = self._entries[-1].digest if self._entries else "sha256:" + "0" * 64
        body = {
            "sequence": len(self._entries) + 1,
            "event_type": event_type,
            "action_id": action_id,
            "occurred_at": occurred_at.isoformat(),
            "attributes": dict(attributes),
            "previous_digest": previous,
        }
        entry = AuditEntry(
            body["sequence"],
            event_type,
            action_id,
            occurred_at,
            dict(attributes),
            previous,
            _digest(body),
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> bool:
        previous = "sha256:" + "0" * 64
        for entry in self._entries:
            body = {
                "sequence": entry.sequence,
                "event_type": entry.event_type,
                "action_id": entry.action_id,
                "occurred_at": entry.occurred_at.isoformat(),
                "attributes": dict(entry.attributes),
                "previous_digest": previous,
            }
            if entry.previous_digest != previous or entry.digest != _digest(body):
                return False
            previous = entry.digest
        return True


@dataclass(frozen=True)
class SourceMutationReceipt:
    receipt_id: str
    action_id: str
    action_digest: str
    idempotency_key: str
    state: ActionState
    started_at: datetime
    completed_at: datetime
    source_version: str
    policy_decision_id: str
    audit_digest: str
    compensation_of: str | None = None

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "receiptId": self.receipt_id,
            "actionId": self.action_id,
            "actionDigest": self.action_digest,
            "idempotencyKey": self.idempotency_key,
            "state": self.state.value,
            "startedAt": self.started_at.isoformat(),
            "completedAt": self.completed_at.isoformat(),
            "sourceVersion": self.source_version,
            "policyDecisionId": self.policy_decision_id,
            "auditDigest": self.audit_digest,
            "compensationOf": self.compensation_of,
        }


class ApprovalRequired(PermissionError):
    pass


class PreviewMismatch(PermissionError):
    pass


class IdempotencyConflict(RuntimeError):
    pass


class ActionExecutionFailed(RuntimeError):
    def __init__(self, receipt: SourceMutationReceipt) -> None:
        super().__init__(f"source action failed: {receipt.action_id}")
        self.receipt = receipt


@dataclass(frozen=True)
class ActionSagaStep:
    action: SourceActionPlan
    approval: ActionApproval | None = None


@dataclass(frozen=True)
class ActionSagaOutcome:
    state: SagaState
    receipts: tuple[SourceMutationReceipt, ...]
    compensation_receipts: tuple[SourceMutationReceipt, ...]
    failed_action_id: str | None


class ActionGateway:
    """Executes mutations locally after preview, policy, approval and replay checks."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        policy: PolicyEvaluator,
        telemetry: TelemetrySink,
        audit: ActionAuditLedger | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.telemetry = telemetry
        self.audit = audit or ActionAuditLedger()
        self.now = now or (lambda: datetime.now(UTC))
        self._idempotency: dict[tuple[str, str], tuple[str, SourceMutationReceipt]] = {}

    async def preview(
        self,
        action: SourceActionPlan,
        identity: RequestIdentity,
        ttl: timedelta = timedelta(minutes=5),
    ) -> ActionPreview:
        connector = self.registry.get(action.source_id, Capability.MUTATE)
        if not connector.profile.consistency.supports_idempotency_key:
            raise ValueError("mutation connector must support source-level idempotency keys")
        decision = await self._authorize(action, identity, "preview")
        created_at = self.now()
        preview = ActionPreview(
            f"preview:{action.action_id}:{action.digest.removeprefix('sha256:')[:12]}",
            action.action_id,
            action.digest,
            identity.policy_digest,
            decision.decision_id,
            created_at,
            created_at + ttl,
            decision.allowed,
            action.approval_mode is ApprovalMode.HUMAN,
            (
                f"{action.source_id}:{action.asset_id}:{action.operation}",
                "conditional:" + ",".join(sorted(action.preconditions)),
            ),
        )
        self.audit.append(
            "previewed",
            action.action_id,
            created_at,
            {"allowed": decision.allowed, "decision_id": decision.decision_id},
        )
        await self._emit("previewed", action, identity, {"allowed": decision.allowed})
        return preview

    async def execute(
        self,
        action: SourceActionPlan,
        preview: ActionPreview,
        identity: RequestIdentity,
        approval: ActionApproval | None = None,
    ) -> SourceMutationReceipt:
        now = self.now()
        self._validate_preview(action, preview, identity, now)
        self._validate_approval(action, approval, identity, now)
        decision = await self._authorize(action, identity, "execute")
        if not decision.allowed:
            raise PolicyDenied(decision)
        key = (action.source_id, action.idempotency_key)
        existing = self._idempotency.get(key)
        if existing is not None:
            digest, receipt = existing
            if digest != action.digest:
                raise IdempotencyConflict("idempotency key was already bound to another action")
            audit = self.audit.append(
                "replayed", action.action_id, now, {"receipt_id": receipt.receipt_id}
            )
            await self._emit("replayed", action, identity, {"receipt_id": receipt.receipt_id})
            return replace(
                receipt,
                state=ActionState.ALREADY_EXECUTED,
                completed_at=now,
                audit_digest=audit.digest,
            )

        connector = self.registry.get(action.source_id, Capability.MUTATE)
        started = now
        try:
            result = await connector.mutate(
                {
                    "action_id": action.action_id,
                    "asset_id": action.asset_id,
                    "operation": action.operation,
                    "parameters": dict(action.parameters),
                    "preconditions": dict(action.preconditions),
                    "idempotency_key": action.idempotency_key,
                }
            )
            if not isinstance(result, Mapping):
                raise TypeError("connector mutation result must be a mapping")
        except Exception as exc:
            completed = self.now()
            audit = self.audit.append(
                ActionState.FAILED.value,
                action.action_id,
                completed,
                {"source_version": "unknown", "reason": "connector_error"},
            )
            receipt = SourceMutationReceipt(
                f"receipt:{action.action_id}:{len(self.audit.entries)}",
                action.action_id,
                action.digest,
                action.idempotency_key,
                ActionState.FAILED,
                started,
                completed,
                "unknown",
                decision.decision_id,
                audit.digest,
            )
            await self._emit(
                ActionState.FAILED.value,
                action,
                identity,
                {"source_version": "unknown"},
            )
            raise ActionExecutionFailed(receipt) from exc
        completed = self.now()
        success = result.get("success") is True and result.get("postconditions_met") is True
        state = ActionState.EXECUTED if success else ActionState.FAILED
        audit = self.audit.append(
            state.value,
            action.action_id,
            completed,
            {"source_version": str(result.get("source_version", "unknown"))},
        )
        receipt = SourceMutationReceipt(
            f"receipt:{action.action_id}:{len(self.audit.entries)}",
            action.action_id,
            action.digest,
            action.idempotency_key,
            state,
            started,
            completed,
            str(result.get("source_version", "unknown")),
            decision.decision_id,
            audit.digest,
        )
        if not success:
            await self._emit(
                state.value, action, identity, {"source_version": receipt.source_version}
            )
            raise ActionExecutionFailed(receipt)
        self._idempotency[key] = (action.digest, receipt)
        await self._emit(state.value, action, identity, {"source_version": receipt.source_version})
        return receipt

    async def compensate(
        self,
        original: SourceActionPlan,
        receipt: SourceMutationReceipt,
        identity: RequestIdentity,
        approval: ActionApproval | None = None,
    ) -> SourceMutationReceipt:
        if original.compensation is None:
            raise ValueError("source action has no declared compensation")
        if receipt.action_digest != original.digest:
            raise ValueError("receipt is not bound to the source action being compensated")
        if receipt.state not in {ActionState.EXECUTED, ActionState.ALREADY_EXECUTED}:
            raise ValueError("only a successful source action can be compensated")
        self._validate_approval(original, approval, identity, self.now(), compensation=True)
        derived = SourceActionPlan(
            f"{original.action_id}:compensate",
            original.source_id,
            original.asset_id,
            original.compensation.operation,
            original.compensation.parameters,
            original.compensation.preconditions,
            f"{original.idempotency_key}:compensate",
            ActionRisk.MEDIUM,
            ApprovalMode.NONE,
            f"compensate {original.action_id}",
        )
        preview = await self.preview(derived, identity)
        compensated = await self.execute(derived, preview, identity)
        audit = self.audit.append(
            "compensated",
            original.action_id,
            self.now(),
            {"compensation_receipt_id": compensated.receipt_id},
        )
        return replace(
            compensated,
            state=ActionState.COMPENSATED,
            audit_digest=audit.digest,
            compensation_of=receipt.receipt_id,
        )

    async def _authorize(
        self, action: SourceActionPlan, identity: RequestIdentity, stage: str
    ) -> PolicyDecision:
        decision = await self.policy.evaluate(
            AuthorizationRequest(
                identity,
                action.source_id,
                Capability.MUTATE,
                (action.asset_id,),
                action.purpose,
                {"risk": action.risk.value, "stage": stage},
                {
                    "operation": action.operation,
                    "precondition_fields": tuple(sorted(action.preconditions)),
                    "action_digest": action.digest,
                },
            )
        )
        await self._emit_event(
            TelemetryEvent(
                "data.harness.action.authorization",
                identity,
                attributes={
                    "source_id": action.source_id,
                    "action_id": action.action_id,
                    "stage": stage,
                    "allowed": decision.allowed,
                    "decision_id": decision.decision_id,
                },
            ),
            action.action_id,
        )
        return decision

    @staticmethod
    def _validate_preview(
        action: SourceActionPlan,
        preview: ActionPreview,
        identity: RequestIdentity,
        now: datetime,
    ) -> None:
        if (
            not preview.allowed
            or preview.action_id != action.action_id
            or preview.action_digest != action.digest
            or preview.policy_digest != identity.policy_digest
            or now >= preview.expires_at
        ):
            raise PreviewMismatch("preview is denied, stale or not bound to this action and policy")

    @staticmethod
    def _validate_approval(
        action: SourceActionPlan,
        approval: ActionApproval | None,
        identity: RequestIdentity,
        now: datetime,
        compensation: bool = False,
    ) -> None:
        if action.approval_mode is ApprovalMode.NONE:
            return
        if approval is None:
            raise ApprovalRequired("human approval is required")
        valid = (
            approval.action_digest == action.digest
            and approval.policy_digest == identity.policy_digest
            and approval.approved_at <= now < approval.expires_at
            and (not compensation or approval.allow_compensation)
        )
        if not valid:
            raise ApprovalRequired("approval is stale, mismatched or excludes compensation")

    async def _emit(
        self,
        stage: str,
        action: SourceActionPlan,
        identity: RequestIdentity,
        attributes: Mapping[str, Scalar],
    ) -> None:
        await self._emit_event(
            TelemetryEvent(
                f"data.harness.action.{stage}",
                identity,
                attributes={
                    "source_id": action.source_id,
                    "action_id": action.action_id,
                    **attributes,
                },
            ),
            action.action_id,
        )

    async def _emit_event(self, event: TelemetryEvent, action_id: str) -> None:
        try:
            await self.telemetry.emit(event)
        except Exception:
            self.audit.append(
                "telemetry-failed",
                action_id,
                self.now(),
                {"event_name": event.name},
            )


class ActionSagaCoordinator:
    """Run governed steps and compensate successful predecessors in reverse order."""

    _controlled_failures = (
        ActionExecutionFailed,
        ApprovalRequired,
        IdempotencyConflict,
        PolicyDenied,
        PreviewMismatch,
        ValueError,
    )

    def __init__(self, gateway: ActionGateway) -> None:
        self.gateway = gateway

    async def run(
        self,
        steps: tuple[ActionSagaStep, ...],
        identity: RequestIdentity,
    ) -> ActionSagaOutcome:
        if not steps:
            raise ValueError("an action saga requires at least one step")
        completed: list[tuple[ActionSagaStep, SourceMutationReceipt]] = []
        for step in steps:
            try:
                preview = await self.gateway.preview(step.action, identity)
                receipt = await self.gateway.execute(step.action, preview, identity, step.approval)
            except self._controlled_failures:
                compensations: list[SourceMutationReceipt] = []
                for completed_step, completed_receipt in reversed(completed):
                    try:
                        compensation = await self.gateway.compensate(
                            completed_step.action,
                            completed_receipt,
                            identity,
                            completed_step.approval,
                        )
                    except self._controlled_failures:
                        return ActionSagaOutcome(
                            SagaState.COMPENSATION_FAILED,
                            tuple(receipt for _, receipt in completed),
                            tuple(compensations),
                            step.action.action_id,
                        )
                    compensations.append(compensation)
                state = SagaState.COMPENSATED if completed else SagaState.FAILED
                return ActionSagaOutcome(
                    state,
                    tuple(receipt for _, receipt in completed),
                    tuple(compensations),
                    step.action.action_id,
                )
            completed.append((step, receipt))
        return ActionSagaOutcome(
            SagaState.COMPLETED,
            tuple(receipt for _, receipt in completed),
            (),
            None,
        )
