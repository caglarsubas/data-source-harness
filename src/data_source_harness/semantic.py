"""Append-only semantic assertions with provenance and bitemporal validity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from .models import LineageRef


class AssertionPredicate(StrEnum):
    SAME_AS = "same_as"
    NOT_SAME_AS = "not_same_as"
    MENTIONS = "mentions"


@dataclass(frozen=True)
class SemanticAssertion:
    assertion_id: str
    subject_id: str
    predicate: AssertionPredicate
    object_id: str
    confidence: float
    asserted_at: datetime
    valid_from: datetime
    valid_to: datetime | None
    policy_digest: str
    lineage: tuple[LineageRef, ...]

    def __post_init__(self) -> None:
        required = (self.assertion_id, self.subject_id, self.object_id, self.policy_digest)
        if any(not item for item in required):
            raise ValueError("assertion identity, entities and policy digest are required")
        if self.subject_id == self.object_id and self.predicate is AssertionPredicate.NOT_SAME_AS:
            raise ValueError("an entity cannot be declared different from itself")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if not self.lineage:
            raise ValueError("semantic assertions require lineage")
        dates = (self.asserted_at, self.valid_from, self.valid_to)
        if any(item is not None and item.tzinfo is None for item in dates):
            raise ValueError("assertion timestamps must be timezone-aware")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")


@dataclass(frozen=True)
class AssertionRetraction:
    assertion_id: str
    retracted_at: datetime
    reason: str

    def __post_init__(self) -> None:
        if self.retracted_at.tzinfo is None or not self.reason:
            raise ValueError("retractions require a timezone-aware timestamp and reason")


class SemanticContradiction(ValueError):
    pass


@dataclass(frozen=True)
class EntityRedirect:
    redirect_id: str
    from_entity_id: str
    to_entity_id: str
    reason: str
    asserted_at: datetime
    lineage: tuple[LineageRef, ...]

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (self.redirect_id, self.from_entity_id, self.to_entity_id, self.reason)
        ):
            raise ValueError("redirect identity, entities and reason are required")
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("entity redirect cannot target itself")
        if self.asserted_at.tzinfo is None or not self.lineage:
            raise ValueError("entity redirect requires time and lineage")


class AssertionGraph:
    def __init__(self) -> None:
        self._assertions: dict[str, SemanticAssertion] = {}
        self._retractions: dict[str, AssertionRetraction] = {}

    def append(self, assertion: SemanticAssertion) -> None:
        if assertion.assertion_id in self._assertions:
            raise ValueError(f"assertion already exists: {assertion.assertion_id}")
        if assertion.predicate is AssertionPredicate.NOT_SAME_AS:
            if assertion.object_id in self.equivalence_cluster(assertion.subject_id):
                raise SemanticContradiction("not_same_as contradicts an active identity cluster")
        elif assertion.predicate is AssertionPredicate.SAME_AS:
            left = self.equivalence_cluster(assertion.subject_id)
            right = self.equivalence_cluster(assertion.object_id)
            if any(
                item.predicate is AssertionPredicate.NOT_SAME_AS
                and (
                    (item.subject_id in left and item.object_id in right)
                    or (item.subject_id in right and item.object_id in left)
                )
                for item in self.active()
            ):
                raise SemanticContradiction("same_as would merge explicitly distinct clusters")
        self._assertions[assertion.assertion_id] = assertion

    def retract(self, retraction: AssertionRetraction) -> None:
        if retraction.assertion_id not in self._assertions:
            raise KeyError(f"unknown assertion: {retraction.assertion_id}")
        if retraction.assertion_id in self._retractions:
            raise ValueError(f"assertion already retracted: {retraction.assertion_id}")
        if retraction.retracted_at < self._assertions[retraction.assertion_id].asserted_at:
            raise ValueError("retraction cannot predate its assertion")
        self._retractions[retraction.assertion_id] = retraction

    def active(
        self,
        at: datetime | None = None,
        *,
        as_known_at: datetime | None = None,
    ) -> tuple[SemanticAssertion, ...]:
        """Return assertions valid at ``at`` and known by ``as_known_at``."""

        valid_at = at or datetime.now(UTC)
        known_at = as_known_at or datetime.now(UTC)
        if valid_at.tzinfo is None or known_at.tzinfo is None:
            raise ValueError("query timestamps must be timezone-aware")
        values = [
            item
            for key, item in self._assertions.items()
            if item.asserted_at <= known_at
            and (key not in self._retractions or known_at < self._retractions[key].retracted_at)
            and item.valid_from <= valid_at
            and (item.valid_to is None or valid_at < item.valid_to)
        ]
        return tuple(values)

    def equivalence_cluster(self, entity_id: str) -> frozenset[str]:
        cluster = {entity_id}
        changed = True
        while changed:
            changed = False
            for assertion in self.active():
                if assertion.predicate is not AssertionPredicate.SAME_AS:
                    continue
                if assertion.subject_id in cluster or assertion.object_id in cluster:
                    before = len(cluster)
                    cluster.update((assertion.subject_id, assertion.object_id))
                    changed = changed or len(cluster) != before
        return frozenset(cluster)
