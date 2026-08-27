"""Reusable in-memory mutation source for independent Phase-4 industry labs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    ConsistencyProfile,
    DataModel,
    RuntimeMode,
)
from data_source_harness.policy import AuthorizationRequest, PolicyDecision


class LabMutationConnector:
    def __init__(
        self, source_id: str, asset_id: str, initial_value: str, *, version: int = 1
    ) -> None:
        self.asset_id = asset_id
        self.value = initial_value
        self.version = version
        self.mutation_count = 0
        self.profile = ConnectorProfile(
            source_id,
            "1.0.0",
            "harness.connector/v1",
            RuntimeMode.PROCESS,
            frozenset({DataModel.TABULAR}),
            frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.MUTATE}),
            frozenset({"credential-reference"}),
            ConsistencyProfile(supports_version_precondition=True, supports_idempotency_key=True),
            ConnectorLimits(),
        )

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        preconditions = request["preconditions"]
        valid = (
            request["asset_id"] == self.asset_id
            and int(preconditions["expectedVersion"]) == self.version
            and str(preconditions["expectedValue"]) == self.value
        )
        if not valid:
            return {
                "success": False,
                "postconditions_met": False,
                "source_version": str(self.version),
            }
        self.value = str(request["parameters"]["newValue"])
        self.version += 1
        self.mutation_count += 1
        return {
            "success": True,
            "postconditions_met": self.value == request["parameters"]["newValue"],
            "source_version": str(self.version),
        }


class BoundedLabActionPolicy:
    def __init__(
        self,
        source_id: str,
        asset_id: str,
        agent_id: str,
        allowed_operations: frozenset[str],
    ) -> None:
        self.source_id = source_id
        self.asset_id = asset_id
        self.agent_id = agent_id
        self.allowed_operations = allowed_operations

    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        allowed = (
            request.identity.agent_id == self.agent_id
            and request.source_id == self.source_id
            and request.capability is Capability.MUTATE
            and request.asset_ids == (self.asset_id,)
            and bool(request.parameters.get("precondition_fields"))
            and request.parameters.get("operation") in self.allowed_operations
        )
        stage = str(request.attributes.get("stage", "unknown"))
        return PolicyDecision(
            allowed,
            f"lab-action:{request.identity.request_id}:{stage}",
            "bounded_action" if allowed else "action_scope_denied",
        )
