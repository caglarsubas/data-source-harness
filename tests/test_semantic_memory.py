from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_source_harness.models import LineageRef
from data_source_harness.policy import RequestIdentity
from data_source_harness.semantic import AssertionPredicate, SemanticAssertion
from data_source_harness.semantic_memory import (
    GovernedSemanticMemory,
    MemoryCandidateStatus,
    MemoryScope,
    SemanticMemoryCandidate,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def candidate() -> SemanticMemoryCandidate:
    return SemanticMemoryCandidate(
        "candidate-1",
        SemanticAssertion(
            "assertion-1",
            "field:incident_state",
            AssertionPredicate.SAME_AS,
            "concept:incident-status",
            0.97,
            NOW,
            NOW,
            None,
            "policy:v1",
            (LineageRef("coldchain.api", "schema", "incident_state"),),
        ),
        "agent.mapper",
        "sha256:schema-v1",
        MemoryScope("org", "solution", frozenset({"agent.mapper", "agent.responder"})),
    )


def identity(agent: str, solution: str = "solution") -> RequestIdentity:
    return RequestIdentity("org", solution, agent, "request", "trace", "policy:v1")


def test_only_reviewed_memory_is_promoted_and_shared_inside_scope() -> None:
    memory = GovernedSemanticMemory()
    item = candidate()
    memory.propose(item)
    with pytest.raises(PermissionError):
        memory.promote(item.candidate_id)
    with pytest.raises(PermissionError, match="human steward"):
        memory.review(item.candidate_id, "agent.reviewer", NOW, approve=True)
    reviewed = memory.review(item.candidate_id, "human:data-steward", NOW, approve=True)
    assert reviewed.status is MemoryCandidateStatus.APPROVED
    promoted = memory.promote(item.candidate_id)
    assert promoted.assertion in memory.graph.active()
    assert memory.view(identity("agent.responder")) == (promoted,)
    assert memory.view(identity("agent.outsider")) == ()
    assert memory.view(identity("agent.responder", "other-solution")) == ()


def test_rejected_candidate_cannot_be_promoted() -> None:
    memory = GovernedSemanticMemory()
    memory.propose(candidate())
    memory.review("candidate-1", "human:data-steward", NOW, approve=False)
    with pytest.raises(PermissionError):
        memory.promote("candidate-1")
