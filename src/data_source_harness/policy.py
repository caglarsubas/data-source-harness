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
