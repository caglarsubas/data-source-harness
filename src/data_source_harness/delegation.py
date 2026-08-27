"""Northbound delegation adapter kept outside the connector implementation ABI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .actions import (
    ActionRisk,
    ApprovalMode,
    CompensationSpec,
    SourceActionPlan,
)
from .models import Scalar
from .policy import RequestIdentity


class DelegationRejected(ValueError):
    pass


class A2AActionDelegationAdapter:
    """Map a bounded A2A-facing envelope into the internal action model."""

    def __init__(self, allowed_operations: frozenset[tuple[str, str]]) -> None:
        self.allowed_operations = allowed_operations

    def to_action_plan(
        self, envelope: Mapping[str, Any], identity: RequestIdentity
    ) -> SourceActionPlan:
        allowed_envelope = {"protocol", "taskId", "requestingAgent", "sourceAction"}
        if set(envelope) != allowed_envelope or envelope.get("protocol") != "a2a/1.0":
            raise DelegationRejected("unsupported or over-broad delegation envelope")
        if not isinstance(envelope.get("taskId"), str) or not envelope["taskId"]:
            raise DelegationRejected("delegation task identity is required")
        if envelope.get("requestingAgent") != identity.agent_id:
            raise DelegationRejected("delegating agent does not match execution identity")
        action = envelope.get("sourceAction")
        if not isinstance(action, Mapping):
            raise DelegationRejected("delegation must contain a structured source action")
        allowed_action = {
            "actionId",
            "sourceId",
            "assetId",
            "operation",
            "parameters",
            "preconditions",
            "idempotencyKey",
            "risk",
            "approvalMode",
            "purpose",
            "compensation",
        }
        if set(action) != allowed_action:
            raise DelegationRejected("delegated source action shape is not exact")
        source_id = str(action["sourceId"])
        operation = str(action["operation"])
        if (source_id, operation) not in self.allowed_operations:
            raise DelegationRejected("delegated operation is not exposed by this adapter")
        compensation_data = action["compensation"]
        compensation = None
        if compensation_data is not None:
            if not isinstance(compensation_data, Mapping):
                raise DelegationRejected("compensation must be structured or null")
            compensation = CompensationSpec(
                str(compensation_data["operation"]),
                self._scalars(compensation_data["parameters"]),
                self._scalars(compensation_data["preconditions"]),
            )
        return SourceActionPlan(
            str(action["actionId"]),
            source_id,
            str(action["assetId"]),
            operation,
            self._scalars(action["parameters"]),
            self._scalars(action["preconditions"]),
            str(action["idempotencyKey"]),
            ActionRisk(str(action["risk"])),
            ApprovalMode(str(action["approvalMode"])),
            str(action["purpose"]),
            compensation,
        )

    @staticmethod
    def _scalars(value: object) -> dict[str, Scalar]:
        if not isinstance(value, Mapping):
            raise DelegationRejected("action parameters and preconditions must be objects")
        result: dict[str, Scalar] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(
                item, (str, int, float, bool, type(None))
            ):
                raise DelegationRejected("delegated values must be scalar")
            result[key] = item
        return result
