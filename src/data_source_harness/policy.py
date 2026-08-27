"""Local authorization seam. Credential material is intentionally out of contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .connector import Capability
from .models import Scalar


@dataclass(frozen=True)
class RequestIdentity:
    organization_id: str
    solution_id: str
    agent_id: str
    request_id: str
    trace_id: str
    policy_digest: str

    def __post_init__(self) -> None:
        if any(not value for value in self.__dict__.values()):
            raise ValueError("all request identity fields are required")


@dataclass(frozen=True)
class AuthorizationRequest:
    identity: RequestIdentity
    source_id: str
    capability: Capability
    asset_ids: tuple[str, ...]
    purpose: str
    attributes: Mapping[str, Scalar] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    decision_id: str
    reason_code: str


class PolicyDenied(PermissionError):
    def __init__(self, decision: PolicyDecision) -> None:
        super().__init__(f"policy denied request: {decision.reason_code}")
        self.decision = decision


class PolicyEvaluator(Protocol):
    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision: ...


class DenyAllPolicy:
    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        return PolicyDecision(False, f"deny:{request.identity.request_id}", "default_deny")


class StaticPolicy:
    """Small deterministic policy for tests and reference labs."""

    def __init__(self, allowed: set[tuple[str, Capability]]) -> None:
        self._allowed = frozenset(allowed)

    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        allowed = (request.source_id, request.capability) in self._allowed
        code = "allowlisted" if allowed else "not_allowlisted"
        return PolicyDecision(allowed, f"static:{request.identity.request_id}:{code}", code)


@dataclass(frozen=True)
class QueryAccessGrant:
    organization_id: str
    solution_id: str
    agent_id: str
    source_id: str
    asset_fields: Mapping[str, frozenset[str]]
    relationships: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        required = (
            self.organization_id,
            self.solution_id,
            self.agent_id,
            self.source_id,
        )
        if any(not value for value in required) or not self.asset_fields:
            raise ValueError(
                "query grants require organization, solution, agent, source and asset scope"
            )


class FieldRelationshipPolicy:
    """Adds query-shape authorization to an existing capability policy."""

    def __init__(
        self,
        base: PolicyEvaluator,
        grants: tuple[QueryAccessGrant, ...],
    ) -> None:
        self.base = base
        self.grants = {
            (
                grant.organization_id,
                grant.solution_id,
                grant.agent_id,
                grant.source_id,
            ): grant
            for grant in grants
        }

    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        base_decision = await self.base.evaluate(request)
        if not base_decision.allowed or request.capability is not Capability.QUERY:
            return base_decision
        grant = self.grants.get(
            (
                request.identity.organization_id,
                request.identity.solution_id,
                request.identity.agent_id,
                request.source_id,
            )
        )
        if grant is None:
            return self._deny(request, "query_grant_missing")
        if not set(request.asset_ids).issubset(grant.asset_fields):
            return self._deny(request, "asset_not_authorized")
        select_by_asset = request.parameters.get("select_by_asset", {})
        if not isinstance(select_by_asset, Mapping) or set(select_by_asset) != set(
            request.asset_ids
        ):
            return self._deny(request, "query_shape_invalid")
        for asset_id, fields in select_by_asset.items():
            if asset_id not in grant.asset_fields or not isinstance(fields, (list, tuple)):
                return self._deny(request, "field_not_authorized")
            if not set(str(item) for item in fields).issubset(grant.asset_fields[asset_id]):
                return self._deny(request, "field_not_authorized")
        relationships = request.parameters.get("relationships", ())
        if not isinstance(relationships, (list, tuple)) or not set(
            str(item) for item in relationships
        ).issubset(grant.relationships):
            return self._deny(request, "relationship_not_authorized")
        filters_by_asset = request.parameters.get("where_by_asset", {})
        if not isinstance(filters_by_asset, Mapping) or not set(filters_by_asset).issubset(
            request.asset_ids
        ):
            return self._deny(request, "query_shape_invalid")
        for asset_id, filters in filters_by_asset.items():
            if not isinstance(filters, Mapping) or not set(filters).issubset(
                grant.asset_fields[asset_id]
            ):
                return self._deny(request, "filter_field_not_authorized")
        return base_decision

    @staticmethod
    def _deny(request: AuthorizationRequest, reason: str) -> PolicyDecision:
        return PolicyDecision(False, f"field:{request.identity.request_id}:{reason}", reason)
