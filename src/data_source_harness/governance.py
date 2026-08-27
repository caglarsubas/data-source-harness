"""Human-governed semantic mapping candidates and schema-drift handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import LineageRef


class MappingStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


@dataclass(frozen=True)
class SemanticMappingCandidate:
    mapping_id: str
    concept_id: str
    source_id: str
    asset_id: str
    field_path: str
    confidence: float
    schema_digest: str
    proposed_at: datetime
    rationale: str
    lineage: tuple[LineageRef, ...]

    def __post_init__(self) -> None:
        required = (
            self.mapping_id,
            self.concept_id,
            self.source_id,
            self.asset_id,
            self.field_path,
            self.schema_digest,
            self.rationale,
        )
        if any(not item for item in required):
            raise ValueError("semantic mapping identity, target, schema and rationale are required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("mapping confidence must be between zero and one")
        if self.proposed_at.tzinfo is None or not self.lineage:
            raise ValueError("semantic mappings require time and lineage")


@dataclass(frozen=True)
class MappingReview:
    mapping_id: str
    status: MappingStatus
    reviewed_by: str
    reviewed_at: datetime
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {MappingStatus.APPROVED, MappingStatus.REJECTED}:
            raise ValueError("a review must approve or reject a mapping")
        if not self.reviewed_by.startswith("human:"):
            raise ValueError("mapping review requires an explicit human steward identity")
        if self.reviewed_at.tzinfo is None or not self.reason:
            raise ValueError("mapping review requires time and reason")


@dataclass(frozen=True)
class MappingDrift:
    mapping_id: str
    source_id: str
    asset_id: str
    expected_schema_digest: str
    observed_schema_digest: str
    detected_at: datetime

    def __post_init__(self) -> None:
        if self.expected_schema_digest == self.observed_schema_digest:
            raise ValueError("drift requires different schema digests")
        if self.detected_at.tzinfo is None:
            raise ValueError("drift detection time must be timezone-aware")


class SemanticMappingRegistry:
    """Append-only candidates; automation can propose but only humans can approve."""

    def __init__(self) -> None:
        self._candidates: dict[str, SemanticMappingCandidate] = {}
        self._reviews: dict[str, MappingReview] = {}
        self._drift: dict[str, MappingDrift] = {}

    def propose(self, candidate: SemanticMappingCandidate) -> None:
        if candidate.mapping_id in self._candidates:
            raise ValueError(f"mapping already exists: {candidate.mapping_id}")
        self._candidates[candidate.mapping_id] = candidate

    def review(self, review: MappingReview) -> None:
        if review.mapping_id not in self._candidates:
            raise KeyError(f"unknown mapping: {review.mapping_id}")
        if review.mapping_id in self._reviews:
            raise ValueError(f"mapping already reviewed: {review.mapping_id}")
        candidate = self._candidates[review.mapping_id]
        if review.reviewed_at < candidate.proposed_at:
            raise ValueError("mapping review cannot predate its proposal")
        self._reviews[review.mapping_id] = review

    def detect_drift(
        self,
        source_id: str,
        asset_id: str,
        observed_schema_digest: str,
        detected_at: datetime,
    ) -> tuple[MappingDrift, ...]:
        found: list[MappingDrift] = []
        for candidate in self.approved(include_quarantined=True):
            if (
                candidate.source_id == source_id
                and candidate.asset_id == asset_id
                and candidate.schema_digest != observed_schema_digest
            ):
                drift = MappingDrift(
                    candidate.mapping_id,
                    source_id,
                    asset_id,
                    candidate.schema_digest,
                    observed_schema_digest,
                    detected_at,
                )
                self._drift[candidate.mapping_id] = drift
                found.append(drift)
        return tuple(found)

    def status(self, mapping_id: str) -> MappingStatus:
        if mapping_id not in self._candidates:
            raise KeyError(mapping_id)
        if mapping_id in self._drift:
            return MappingStatus.QUARANTINED
        review = self._reviews.get(mapping_id)
        return review.status if review else MappingStatus.PROPOSED

    def approved(
        self, *, include_quarantined: bool = False
    ) -> tuple[SemanticMappingCandidate, ...]:
        values = [
            candidate
            for mapping_id, candidate in self._candidates.items()
            if self._reviews.get(mapping_id)
            and self._reviews[mapping_id].status is MappingStatus.APPROVED
            and (include_quarantined or mapping_id not in self._drift)
        ]
        return tuple(sorted(values, key=lambda item: item.mapping_id))

    def approved_for(self, concept_id: str) -> tuple[SemanticMappingCandidate, ...]:
        return tuple(item for item in self.approved() if item.concept_id == concept_id)
