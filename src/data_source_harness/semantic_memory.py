"""Governed promotion of semantic candidates into cross-agent shared memory."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .policy import RequestIdentity
from .semantic import AssertionGraph, SemanticAssertion


class MemoryCandidateStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROMOTED = "promoted"


@dataclass(frozen=True)
class MemoryScope:
    organization_id: str
    solution_id: str
    agent_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not self.organization_id or not self.solution_id or not self.agent_ids:
            raise ValueError("memory scope requires organization, solution and agents")

    def allows(self, identity: RequestIdentity) -> bool:
        return (
            identity.organization_id == self.organization_id
            and identity.solution_id == self.solution_id
            and identity.agent_id in self.agent_ids
        )


@dataclass(frozen=True)
class SemanticMemoryCandidate:
    candidate_id: str
    assertion: SemanticAssertion
    proposed_by: str
    source_schema_digest: str
    scope: MemoryScope
    status: MemoryCandidateStatus = MemoryCandidateStatus.PROPOSED
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.proposed_by or not self.source_schema_digest:
            raise ValueError("memory candidates require identity, proposer and schema digest")


@dataclass(frozen=True)
class PromotedSemanticMemory:
    candidate_id: str
    assertion: SemanticAssertion
    scope: MemoryScope
    promoted_by: str
    promoted_at: datetime


class GovernedSemanticMemory:
    """Local adapter for ADLC-owned memory contracts and promotion decisions."""

    def __init__(self, graph: AssertionGraph | None = None) -> None:
        self.graph = graph or AssertionGraph()
        self._candidates: dict[str, SemanticMemoryCandidate] = {}
        self._promoted: dict[str, PromotedSemanticMemory] = {}

    def propose(self, candidate: SemanticMemoryCandidate) -> None:
        if candidate.candidate_id in self._candidates:
            raise ValueError(f"memory candidate already exists: {candidate.candidate_id}")
        self._candidates[candidate.candidate_id] = candidate

    def review(
        self,
        candidate_id: str,
        reviewer_id: str,
        reviewed_at: datetime,
        *,
        approve: bool,
    ) -> SemanticMemoryCandidate:
        if not reviewer_id.startswith("human:"):
            raise PermissionError("semantic memory review requires a human steward")
        if reviewed_at.tzinfo is None:
            raise ValueError("memory review time must be timezone-aware")
        candidate = self._candidates[candidate_id]
        if candidate.status is not MemoryCandidateStatus.PROPOSED:
            raise ValueError("memory candidate has already been reviewed")
        reviewed = replace(
            candidate,
            status=MemoryCandidateStatus.APPROVED if approve else MemoryCandidateStatus.REJECTED,
            reviewed_by=reviewer_id,
            reviewed_at=reviewed_at,
        )
        self._candidates[candidate_id] = reviewed
        return reviewed

    def promote(self, candidate_id: str) -> PromotedSemanticMemory:
        candidate = self._candidates[candidate_id]
        if candidate.status is not MemoryCandidateStatus.APPROVED:
            raise PermissionError("only an approved semantic memory candidate can be promoted")
        assert candidate.reviewed_by is not None
        assert candidate.reviewed_at is not None
        self.graph.append(candidate.assertion)
        record = PromotedSemanticMemory(
            candidate.candidate_id,
            candidate.assertion,
            candidate.scope,
            candidate.reviewed_by,
            candidate.reviewed_at,
        )
        self._promoted[candidate_id] = record
        self._candidates[candidate_id] = replace(candidate, status=MemoryCandidateStatus.PROMOTED)
        return record

    def view(self, identity: RequestIdentity) -> tuple[PromotedSemanticMemory, ...]:
        return tuple(
            self._promoted[key]
            for key in sorted(self._promoted)
            if self._promoted[key].scope.allows(identity)
        )

    def candidate(self, candidate_id: str) -> SemanticMemoryCandidate:
        return self._candidates[candidate_id]
