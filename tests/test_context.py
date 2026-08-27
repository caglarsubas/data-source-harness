from datetime import UTC, datetime

import pytest

from data_source_harness.context import ContextEnvelope, ContextOutcome
from data_source_harness.coverage import CoverageExclusion, CoverageStatement, SourceCoverage
from data_source_harness.models import LineageRef
from data_source_harness.routing import RouteDecision, RouteStatus, SelectedRoute

NOW = datetime(2026, 8, 27, tzinfo=UTC)
LINEAGE = (LineageRef("erp", "orders", "SO1"),)


def selected_route() -> RouteDecision:
    return RouteDecision(
        "req-1",
        RouteStatus.SELECTED,
        (SelectedRoute("erp", "orders", ("error",), ("m1",), 0.95, "42", LINEAGE),),
        (),
        (),
    )


def test_answer_requires_complete_coverage_and_exact_provenance() -> None:
    coverage = CoverageStatement("req-1", NOW, (SourceCoverage("erp", ("orders",), True),))
    answer = ContextEnvelope(
        "req-1", ContextOutcome.ANSWER, "E21 is correlated", selected_route(), coverage, LINEAGE
    )
    assert answer.outcome is ContextOutcome.ANSWER
    with pytest.raises(ValueError, match="complete coverage"):
        ContextEnvelope(
            "req-1",
            ContextOutcome.ANSWER,
            "unsupported",
            selected_route(),
            CoverageStatement(
                "req-1",
                NOW,
                (),
                (CoverageExclusion("erp", "stale", "watermark exceeded"),),
            ),
            LINEAGE,
        )


def test_ambiguous_context_is_escalation_not_answer() -> None:
    route = RouteDecision(
        "req-1", RouteStatus.ESCALATION_REQUIRED, (), ("error",), ("ambiguous_mapping:error",)
    )
    coverage = CoverageStatement(
        "req-1", NOW, (), (CoverageExclusion("erp", "ambiguous", "steward review required"),)
    )
    context = ContextEnvelope(
        "req-1",
        ContextOutcome.ESCALATION,
        None,
        route,
        coverage,
        (),
        route.reason_codes,
    )
    assert context.content is None


def test_context_rejects_coverage_from_another_request() -> None:
    with pytest.raises(ValueError, match="coverage request identities"):
        ContextEnvelope(
            "req-1",
            ContextOutcome.ANSWER,
            "unsupported mix",
            selected_route(),
            CoverageStatement("req-other", NOW, (SourceCoverage("erp", ("orders",), True),)),
            LINEAGE,
        )
