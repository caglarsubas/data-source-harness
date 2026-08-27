import json

import pytest

from data_source_harness.conformance import run_connector_conformance
from data_source_harness.context import ContextOutcome
from data_source_harness.promotion import EvidenceKind
from data_source_harness.routing import RouteStatus
from reference_labs.white_goods.certify_phase2 import certify_phase2
from reference_labs.white_goods.lab import LAB_ROOT
from reference_labs.white_goods.phase2 import (
    SemanticGraphConnector,
    ambiguous_context,
    bounded_e21_plan,
    covered_route,
    execute_bounded_e21_plan,
    grounded_e21_context,
    promotion_readiness,
)


def test_covered_route_uses_four_approved_fresh_sources() -> None:
    route = covered_route()
    assert route.complete
    assert len(route.routes) == 4
    assert {concept for item in route.routes for concept in item.concept_ids} == {
        "service.error-code",
        "telemetry.error-code",
        "diagnosis.guidance",
        "appointment.status",
    }


@pytest.mark.asyncio
async def test_graph_source_family_passes_connector_conformance() -> None:
    report = await run_connector_conformance(SemanticGraphConnector())
    assert report.passed


@pytest.mark.asyncio
async def test_grounded_context_has_exact_four_source_provenance() -> None:
    context = await grounded_e21_context()
    assert context.outcome is ContextOutcome.ANSWER
    assert context.coverage.is_complete
    assert len(context.lineage) == 7
    assert len({item.source_id for item in context.lineage}) == 4


def test_ambiguous_mapping_escalates_without_answer_content() -> None:
    context = ambiguous_context()
    assert context.outcome is ContextOutcome.ESCALATION
    assert context.route.status is RouteStatus.ESCALATION_REQUIRED
    assert context.content is None


def test_bounded_plan_and_promotion_boundary_are_explicit() -> None:
    plan = bounded_e21_plan()
    assert plan.limit == 20 and plan.estimated_rows == 20
    readiness = promotion_readiness()
    assert not readiness.ready_for_adlc_decision
    assert set(readiness.missing_kinds) == set(EvidenceKind)
    assert promotion_readiness(simulate_all_evidence=True).ready_for_adlc_decision


@pytest.mark.asyncio
async def test_bounded_plan_executes_end_to_end_against_pilot_connector() -> None:
    batches = await execute_bounded_e21_plan()
    assert len(batches) == 2
    assert {item.asset_id for batch in batches for item in batch.lineage} == {
        "service_orders",
        "installed_products",
    }
    assert {row["error_code"] for row in batches[0].payload} == {"E21"}


@pytest.mark.asyncio
async def test_phase2_certificate_passes_every_declared_metric() -> None:
    report = await certify_phase2()
    assert report.passed, report
    assert all(check.passed for check in report.checks)
    assert all(metric.passed for metric in report.metrics)
    gqm = json.loads((LAB_ROOT / "phase2-gqm-plan.json").read_text(encoding="utf-8"))
    assert {item["metricId"] for item in gqm["metrics"]} == {
        item.metric_id for item in report.metrics
    }
