from datetime import UTC, datetime, timedelta

from data_source_harness.freshness import FreshnessObservation, FreshnessRegistry, FreshnessSLO
from data_source_harness.governance import (
    MappingReview,
    MappingStatus,
    SemanticMappingCandidate,
    SemanticMappingRegistry,
)
from data_source_harness.models import LineageRef
from data_source_harness.routing import RouteRequest, RouteStatus, SemanticSourceRouter

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def mapping(mapping_id: str, source: str, confidence: float = 0.95) -> SemanticMappingCandidate:
    return SemanticMappingCandidate(
        mapping_id,
        "service.error-code",
        source,
        "orders",
        "error_code",
        confidence,
        "sha256:schema",
        NOW,
        "matched",
        (LineageRef(source, "orders", field_path="error_code"),),
    )


def approved_registry(*candidates: SemanticMappingCandidate) -> SemanticMappingRegistry:
    registry = SemanticMappingRegistry()
    for item in candidates:
        registry.propose(item)
        registry.review(
            MappingReview(item.mapping_id, MappingStatus.APPROVED, "human:steward", NOW, "ok")
        )
    return registry


def freshness(*sources: str, age: timedelta = timedelta(minutes=1)) -> FreshnessRegistry:
    registry = FreshnessRegistry()
    for source in sources:
        registry.record(FreshnessObservation(source, "orders", NOW, NOW - age, "42"))
    return registry


def request() -> RouteRequest:
    return RouteRequest(
        "req-1", ("service.error-code",), 2, 0.8, 0.02, FreshnessSLO(timedelta(minutes=5))
    )


def test_router_selects_fresh_steward_approved_mapping() -> None:
    decision = SemanticSourceRouter(
        approved_registry(mapping("m1", "erp")), freshness("erp")
    ).route(request(), NOW)
    assert decision.status is RouteStatus.SELECTED
    assert decision.routes[0].mapping_ids == ("m1",)
    assert decision.routes[0].watermark == "42"


def test_router_escalates_ambiguous_equal_candidates() -> None:
    decision = SemanticSourceRouter(
        approved_registry(mapping("m1", "erp"), mapping("m2", "warehouse", 0.94)),
        freshness("erp", "warehouse"),
    ).route(request(), NOW)
    assert decision.status is RouteStatus.ESCALATION_REQUIRED
    assert decision.reason_codes == ("ambiguous_mapping:service.error-code",)


def test_router_refuses_stale_or_drift_quarantined_mapping() -> None:
    mappings = approved_registry(mapping("m1", "erp"))
    mappings.detect_drift("erp", "orders", "sha256:changed", NOW)
    decision = SemanticSourceRouter(mappings, freshness("erp", age=timedelta(minutes=10))).route(
        request(), NOW
    )
    assert decision.status is RouteStatus.REFUSED
    assert decision.uncovered_concepts == ("service.error-code",)
