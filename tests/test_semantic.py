from datetime import UTC, datetime, timedelta

import pytest

from data_source_harness.models import LineageRef
from data_source_harness.semantic import (
    AssertionGraph,
    AssertionPredicate,
    AssertionRetraction,
    EntityRedirect,
    SemanticAssertion,
    SemanticContradiction,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def assertion(
    assertion_id: str, predicate: AssertionPredicate, left: str, right: str
) -> SemanticAssertion:
    return SemanticAssertion(
        assertion_id,
        left,
        predicate,
        right,
        0.9,
        NOW,
        NOW,
        None,
        "sha256:policy",
        (LineageRef("erp", "customers", "1"),),
    )


def test_same_as_builds_transitive_cluster_but_mentions_does_not() -> None:
    graph = AssertionGraph()
    graph.append(assertion("a1", AssertionPredicate.SAME_AS, "a", "b"))
    graph.append(assertion("a2", AssertionPredicate.SAME_AS, "b", "c"))
    graph.append(assertion("a3", AssertionPredicate.MENTIONS, "c", "d"))
    assert graph.equivalence_cluster("a") == frozenset({"a", "b", "c"})


def test_conflicting_identity_assertion_fails_until_retracted() -> None:
    graph = AssertionGraph()
    graph.append(assertion("a1", AssertionPredicate.SAME_AS, "a", "b"))
    with pytest.raises(SemanticContradiction):
        graph.append(assertion("a2", AssertionPredicate.NOT_SAME_AS, "b", "a"))
    graph.retract(AssertionRetraction("a1", NOW, "corrected by steward"))
    graph.append(assertion("a2", AssertionPredicate.NOT_SAME_AS, "b", "a"))


def test_entity_redirect_is_non_destructive_and_lineage_bound() -> None:
    redirect = EntityRedirect(
        "r1",
        "crm:7",
        "canonical:42",
        "steward-approved merge",
        NOW,
        (LineageRef("crm", "customers", "7"),),
    )
    assert redirect.from_entity_id != redirect.to_entity_id


def test_transitive_identity_contradiction_is_rejected() -> None:
    graph = AssertionGraph()
    graph.append(assertion("a1", AssertionPredicate.SAME_AS, "a", "b"))
    graph.append(assertion("a2", AssertionPredicate.SAME_AS, "b", "c"))
    with pytest.raises(SemanticContradiction, match="identity cluster"):
        graph.append(assertion("a3", AssertionPredicate.NOT_SAME_AS, "a", "c"))


def test_identity_merge_cannot_cross_a_not_same_as_boundary() -> None:
    graph = AssertionGraph()
    graph.append(assertion("a1", AssertionPredicate.NOT_SAME_AS, "a", "c"))
    graph.append(assertion("a2", AssertionPredicate.SAME_AS, "a", "b"))
    with pytest.raises(SemanticContradiction, match="distinct clusters"):
        graph.append(assertion("a3", AssertionPredicate.SAME_AS, "b", "c"))


def test_active_enforces_valid_and_transaction_time_even_with_default_query() -> None:
    graph = AssertionGraph()
    expired = SemanticAssertion(
        "expired",
        "a",
        AssertionPredicate.MENTIONS,
        "b",
        0.9,
        NOW - timedelta(days=3),
        NOW - timedelta(days=2),
        NOW - timedelta(days=1),
        "sha256:policy",
        (LineageRef("erp", "customers", "1"),),
    )
    future_asserted = SemanticAssertion(
        "future",
        "a",
        AssertionPredicate.MENTIONS,
        "c",
        0.9,
        NOW + timedelta(days=2),
        NOW,
        None,
        "sha256:policy",
        (LineageRef("erp", "customers", "1"),),
    )
    graph.append(expired)
    graph.append(future_asserted)
    assert graph.active(NOW, as_known_at=NOW) == ()


def test_active_supports_independent_valid_and_transaction_time() -> None:
    graph = AssertionGraph()
    item = assertion("a1", AssertionPredicate.MENTIONS, "a", "b")
    graph.append(item)
    graph.retract(AssertionRetraction("a1", NOW + timedelta(days=2), "later correction"))
    assert graph.active(NOW + timedelta(days=1), as_known_at=NOW + timedelta(days=1)) == (item,)
    assert graph.active(NOW + timedelta(days=1), as_known_at=NOW + timedelta(days=3)) == ()
