"""Semantic- and freshness-aware source routing with explicit escalation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .freshness import FreshnessBreachAction, FreshnessRegistry, FreshnessSLO
from .governance import SemanticMappingCandidate, SemanticMappingRegistry
from .models import LineageRef


class RouteStatus(StrEnum):
    SELECTED = "selected"
    REFUSED = "refused"
    ESCALATION_REQUIRED = "escalation_required"


@dataclass(frozen=True)
class RouteRequest:
    request_id: str
    concept_ids: tuple[str, ...]
    max_sources: int
    minimum_confidence: float
    ambiguity_delta: float
    freshness_slo: FreshnessSLO

    def __post_init__(self) -> None:
        if not self.request_id or not self.concept_ids or self.max_sources <= 0:
            raise ValueError("route request requires identity, concepts and a source bound")
        if not 0 <= self.minimum_confidence <= 1 or not 0 <= self.ambiguity_delta <= 1:
            raise ValueError("routing confidence values must be between zero and one")


@dataclass(frozen=True)
class SelectedRoute:
    source_id: str
    asset_id: str
    concept_ids: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    score: float
    watermark: str
    lineage: tuple[LineageRef, ...]


@dataclass(frozen=True)
class RouteDecision:
    request_id: str
    status: RouteStatus
    routes: tuple[SelectedRoute, ...]
    uncovered_concepts: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.status is RouteStatus.SELECTED and not self.uncovered_concepts


class SemanticSourceRouter:
    def __init__(self, mappings: SemanticMappingRegistry, freshness: FreshnessRegistry) -> None:
        self.mappings = mappings
        self.freshness = freshness

    def route(self, request: RouteRequest, at: datetime) -> RouteDecision:
        selected: dict[tuple[str, str], list[SemanticMappingCandidate]] = {}
        uncovered: list[str] = []
        ambiguous: list[str] = []
        stale: list[str] = []
        freshness_refused: list[str] = []
        degraded: list[str] = []
        degraded_candidates: set[str] = set()
        for concept_id in request.concept_ids:
            candidates = [
                item
                for item in self.mappings.approved_for(concept_id)
                if item.confidence >= request.minimum_confidence
            ]
            eligible: list[tuple[SemanticMappingCandidate, str]] = []
            for candidate in candidates:
                assessment = self.freshness.assess(
                    candidate.source_id, candidate.asset_id, request.freshness_slo, at
                )
                if assessment.fresh:
                    eligible.append((candidate, assessment.watermark))
                elif assessment.action is FreshnessBreachAction.DEGRADE:
                    eligible.append((candidate, assessment.watermark))
                    degraded_candidates.add(candidate.mapping_id)
                elif assessment.action is FreshnessBreachAction.REFUSE:
                    freshness_refused.append(concept_id)
                else:
                    stale.append(concept_id)
            eligible.sort(key=lambda item: (-item[0].confidence, item[0].mapping_id))
            if not eligible:
                uncovered.append(concept_id)
                continue
            if (
                len(eligible) > 1
                and eligible[0][0].confidence - eligible[1][0].confidence <= request.ambiguity_delta
            ):
                ambiguous.append(concept_id)
                continue
            winner, _ = eligible[0]
            if winner.mapping_id in degraded_candidates:
                degraded.append(concept_id)
            selected.setdefault((winner.source_id, winner.asset_id), []).append(winner)
        if ambiguous:
            return RouteDecision(
                request.request_id,
                RouteStatus.ESCALATION_REQUIRED,
                (),
                tuple(sorted(set(uncovered + ambiguous))),
                tuple(f"ambiguous_mapping:{item}" for item in sorted(set(ambiguous))),
            )
        if uncovered or len(selected) > request.max_sources:
            reasons = [f"uncovered:{item}" for item in sorted(set(uncovered))]
            if stale:
                reasons.extend(f"stale:{item}" for item in sorted(set(stale)))
            if freshness_refused:
                reasons.extend(
                    f"freshness_refused:{item}" for item in sorted(set(freshness_refused))
                )
            if len(selected) > request.max_sources:
                reasons.append("source_bound_exceeded")
            return RouteDecision(
                request.request_id,
                RouteStatus.REFUSED,
                (),
                tuple(sorted(set(uncovered))),
                tuple(reasons),
            )
        routes: list[SelectedRoute] = []
        for (source_id, asset_id), candidates in sorted(selected.items()):
            assessment = self.freshness.assess(source_id, asset_id, request.freshness_slo, at)
            routes.append(
                SelectedRoute(
                    source_id,
                    asset_id,
                    tuple(sorted(item.concept_id for item in candidates)),
                    tuple(sorted(item.mapping_id for item in candidates)),
                    sum(item.confidence for item in candidates) / len(candidates),
                    assessment.watermark,
                    tuple(lineage for item in candidates for lineage in item.lineage),
                )
            )
        return RouteDecision(
            request.request_id,
            RouteStatus.SELECTED,
            tuple(routes),
            (),
            tuple(f"freshness_degraded:{item}" for item in sorted(set(degraded))),
        )
