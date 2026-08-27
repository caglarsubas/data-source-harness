from datetime import UTC, datetime

import pytest

from data_source_harness.governance import (
    MappingReview,
    MappingStatus,
    SemanticMappingCandidate,
    SemanticMappingRegistry,
)
from data_source_harness.models import LineageRef

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def candidate(mapping_id: str = "map-1") -> SemanticMappingCandidate:
    return SemanticMappingCandidate(
        mapping_id,
        "service.error-code",
        "erp",
        "orders",
        "error_code",
        0.95,
        "sha256:old",
        NOW,
        "matching schema and values",
        (LineageRef("erp", "orders", field_path="error_code"),),
    )


def test_mapping_requires_human_review_before_routing() -> None:
    registry = SemanticMappingRegistry()
    registry.propose(candidate())
    assert registry.approved_for("service.error-code") == ()
    with pytest.raises(ValueError, match="human steward"):
        registry.review(MappingReview("map-1", MappingStatus.APPROVED, "agent:1", NOW, "ok"))
    registry.review(
        MappingReview("map-1", MappingStatus.APPROVED, "human:data-steward", NOW, "verified")
    )
    assert registry.approved_for("service.error-code") == (candidate(),)


def test_schema_drift_quarantines_without_rewriting_mapping() -> None:
    registry = SemanticMappingRegistry()
    registry.propose(candidate())
    registry.review(
        MappingReview("map-1", MappingStatus.APPROVED, "human:data-steward", NOW, "verified")
    )
    drift = registry.detect_drift("erp", "orders", "sha256:new", NOW)
    assert drift[0].expected_schema_digest == "sha256:old"
    assert registry.status("map-1") is MappingStatus.QUARANTINED
    assert registry.approved_for("service.error-code") == ()
