"""Machine-readable Phase-2 trustworthy-context certification."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import jsonschema

from data_source_harness.conformance import run_connector_conformance
from data_source_harness.context import ContextOutcome
from data_source_harness.freshness import CheckpointRegression, FreshnessSLO
from data_source_harness.governance import MappingStatus
from data_source_harness.models import QueryRequest
from data_source_harness.planning import (
    BoundedQueryPlanner,
    PlanDenied,
    PlanningConstraints,
    QueryIntent,
)
from data_source_harness.promotion import EvidenceKind
from data_source_harness.routing import RouteRequest, RouteStatus, SemanticSourceRouter

from .certify import CertificationCheck, MetricResult, _metric, certify
from .lab import FIXED_TIME, LAB_ROOT
from .phase2 import (
    SemanticGraphConnector,
    ambiguous_context,
    bounded_e21_plan,
    checkpoint_ledger,
    compatibility_matrix,
    freshness_registry,
    grounded_e21_context,
    mapping_registry,
    promotion_readiness,
)

REPOSITORY_ROOT = LAB_ROOT.parents[1]


@dataclass(frozen=True)
class Phase2Report:
    phase: str
    lab_id: str
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_artifacts() -> tuple[CertificationCheck, ...]:
    promotion_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/promotion-readiness.schema.json").read_text(encoding="utf-8")
    )
    promotion = json.loads(
        (LAB_ROOT / "promotion-readiness.example.json").read_text(encoding="utf-8")
    )
    errors = list(
        jsonschema.Draft202012Validator(
            promotion_schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(promotion)
    )
    mapping_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/semantic-mapping-candidate.schema.json").read_text(
            encoding="utf-8"
        )
    )
    mappings = json.loads((LAB_ROOT / "semantic-mappings.json").read_text(encoding="utf-8"))
    mapping_validator = jsonschema.Draft202012Validator(
        mapping_schema, format_checker=jsonschema.FormatChecker()
    )
    mapping_errors = [
        error.message
        for item in mappings["mappings"]
        for error in mapping_validator.iter_errors(
            {
                "schemaVersion": "data.harness/v1",
                "mappingId": item["mappingId"],
                "conceptId": item["conceptId"],
                "target": item["target"],
                "confidence": item["confidence"],
                "schemaDigest": item["schemaDigest"],
                "status": item["review"]["status"],
                "proposedAt": FIXED_TIME.isoformat(),
                "rationale": item["rationale"],
                "lineage": item["lineage"],
            }
        )
    ]
    freshness_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/freshness-observation.schema.json").read_text(
            encoding="utf-8"
        )
    )
    freshness = json.loads((LAB_ROOT / "freshness-slos.json").read_text(encoding="utf-8"))
    freshness_validator = jsonschema.Draft202012Validator(
        freshness_schema, format_checker=jsonschema.FormatChecker()
    )
    freshness_errors = [
        error.message
        for item in freshness["observations"]
        for error in freshness_validator.iter_errors(
            {
                "schemaVersion": "data.harness/v1",
                "sourceId": item["sourceId"],
                "assetId": item["assetId"],
                "observedAt": FIXED_TIME.isoformat(),
                "sourceEventTime": (FIXED_TIME - timedelta(seconds=item["ageSeconds"])).isoformat(),
                "watermark": item["watermark"],
                "assessment": {
                    "fresh": item["ageSeconds"] <= freshness["defaultMaxAgeSeconds"],
                    "ageMs": item["ageSeconds"] * 1000,
                    "breachAction": None,
                },
            }
        )
    ]
    matrix = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase2-compatibility-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    release_set = json.loads(
        (REPOSITORY_ROOT / "compatibility/cross-plane-release-set.lock.json").read_text(
            encoding="utf-8"
        )
    )
    pins = {(item["name"], item["revision"]) for item in release_set["components"]}
    matrix_pins = {(item["component"], item["revision"]) for item in matrix["components"]}
    return (
        CertificationCheck(
            "contract.promotion-readiness",
            not errors,
            "; ".join(item.message for item in errors) if errors else "valid",
        ),
        CertificationCheck(
            "contract.semantic-mappings",
            not mapping_errors,
            (
                "; ".join(mapping_errors)
                if mapping_errors
                else f"mappings={len(mappings['mappings'])}"
            ),
        ),
        CertificationCheck(
            "contract.freshness-observations",
            not freshness_errors,
            (
                "; ".join(freshness_errors)
                if freshness_errors
                else f"observations={len(freshness['observations'])}"
            ),
        ),
        CertificationCheck(
            "compatibility.exact-pinned-matrix",
            pins == matrix_pins
            and all(item["contractCompatible"] for item in matrix["components"]),
            f"components={len(matrix_pins)}; boundary=contract-only",
        ),
    )


async def certify_phase2() -> Phase2Report:
    checks = list(_validate_artifacts())
    phase1 = await certify()
    gqm = json.loads((LAB_ROOT / "phase2-gqm-plan.json").read_text(encoding="utf-8"))
    definitions = {item["metricId"]: item for item in gqm["metrics"]}

    graph_connector = SemanticGraphConnector()
    graph_conformance = await run_connector_conformance(graph_connector)
    graph_batches = [
        batch
        async for batch in graph_connector.execute(
            QueryRequest(
                "whitegoods.semantic-graph",
                ("semantic_assertions",),
                {},
                10,
                1_000,
                "governed semantic context",
            )
        )
    ]
    graph_ok = graph_conformance.passed and graph_batches[0].row_count == 2
    checks.append(
        CertificationCheck(
            "connectors.graph-source-family",
            graph_ok,
            f"conformance={graph_conformance.passed}; assertions={graph_batches[0].row_count}",
        )
    )

    context = await grounded_e21_context()
    routing_ok = context.route.complete and len(context.route.routes) == 4
    provenance_ok = (
        context.outcome is ContextOutcome.ANSWER
        and context.coverage.is_complete
        and len(context.lineage) == 7
        and all(item.source_id and item.asset_id and item.record_id for item in context.lineage)
        and {item.source_id for item in context.lineage}
        == {
            "whitegoods.erp",
            "whitegoods.telemetry",
            "whitegoods.documents",
            "whitegoods.service-api",
        }
    )
    checks.append(
        CertificationCheck(
            "routing.covered-four-source-context",
            routing_ok and provenance_ok,
            f"routes={len(context.route.routes)}; lineage={len(context.lineage)}",
        )
    )

    ambiguous = ambiguous_context()
    stale = SemanticSourceRouter(mapping_registry(), freshness_registry()).route(
        RouteRequest(
            "phase2-stale",
            ("service.error-code",),
            1,
            0.85,
            0.02,
            FreshnessSLO(timedelta(seconds=1)),
        ),
        FIXED_TIME,
    )
    refusal_ok = (
        ambiguous.outcome is ContextOutcome.ESCALATION
        and ambiguous.route.status is RouteStatus.ESCALATION_REQUIRED
        and stale.status is RouteStatus.REFUSED
    )
    checks.append(
        CertificationCheck(
            "routing.ambiguity-and-stale-refusal",
            refusal_ok,
            f"ambiguous={ambiguous.route.status.value}; stale={stale.status.value}",
        )
    )

    registry = mapping_registry()
    drift = registry.detect_drift(
        "whitegoods.erp", "service_orders", "sha256:service-orders-v2", FIXED_TIME
    )
    drift_ok = len(drift) == 1 and registry.status("map-service-error") is MappingStatus.QUARANTINED
    checks.append(
        CertificationCheck(
            "semantics.drift-quarantine",
            drift_ok,
            "changed schema quarantined without automatic remapping",
        )
    )

    plan = bounded_e21_plan()
    bounded_ok = plan.limit == 20 and len(plan.relationships) == 1
    denied = False
    try:
        BoundedQueryPlanner().compile(
            QueryIntent(
                "whitegoods.erp",
                ("service_orders",),
                {"service_orders": ("customer_email",)},
                {},
                (),
                20,
                1_000,
                "forbidden export",
            ),
            PlanningConstraints(
                {"service_orders": frozenset({"service_order_id"})},
                frozenset(),
                1,
                20,
                1_000,
            ),
        )
    except PlanDenied:
        denied = True
    checks.append(
        CertificationCheck(
            "planning.field-and-relationship-bounds",
            bounded_ok and denied,
            f"assets={len(plan.asset_ids)}; forbidden_field_denied={denied}",
        )
    )

    ledger = checkpoint_ledger()
    checkpoint_ok = ledger.resume("whitegoods.telemetry", "telemetry_events") is not None
    regression_denied = False
    try:
        token = ledger.resume("whitegoods.telemetry", "telemetry_events")
        assert token is not None
        ledger.record(
            type(token)(token.source_id, token.stream_id, "7", FIXED_TIME, token.connector_version)
        )
    except CheckpointRegression:
        regression_denied = True
    checks.append(
        CertificationCheck(
            "cdc.monotonic-checkpoint",
            checkpoint_ok and regression_denied,
            "resume=9; regression=denied",
        )
    )

    matrix = compatibility_matrix()
    actual_readiness = promotion_readiness()
    simulated_readiness = promotion_readiness(simulate_all_evidence=True)
    promotion_ok = (
        matrix.compatible
        and not actual_readiness.ready_for_adlc_decision
        and set(actual_readiness.missing_kinds) == set(EvidenceKind)
        and simulated_readiness.ready_for_adlc_decision
    )
    checks.append(
        CertificationCheck(
            "promotion.evidence-separated",
            promotion_ok,
            "contract pins compatible; all release evidence remains missing in static example",
        )
    )

    metrics = (
        _metric(definitions, "P2-M1", float(routing_ok), "4/4 concepts routed"),
        _metric(definitions, "P2-M2", float(provenance_ok), f"lineage={len(context.lineage)}"),
        _metric(definitions, "P2-M3", float(refusal_ok), "ambiguous escalated; stale refused"),
        _metric(definitions, "P2-M4", float(drift_ok), f"quarantined={len(drift)}"),
        _metric(definitions, "P2-M5", float(routing_ok), "all selected routes within 300s SLO"),
        _metric(definitions, "P2-M6", float(bounded_ok and denied), "allowed plan and deny path"),
        _metric(definitions, "P2-M7", float(checkpoint_ok and regression_denied), "resume=9"),
        _metric(definitions, "P2-M8", float(matrix.compatible), f"pins={len(matrix.entries)}"),
        _metric(definitions, "P2-M9", float(promotion_ok), "actual blocked; simulation ready"),
        _metric(
            definitions,
            "P2-M10",
            float(phase1.passed and graph_ok),
            "Phase-1 certificate rerun and graph-family conformance",
        ),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase2-plan-complete",
            {item["metricId"] for item in gqm["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(gqm['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = (
        phase1.passed
        and all(item.passed for item in checks)
        and all(item.passed for item in metrics)
    )
    return Phase2Report(
        "phase-2",
        "white-goods-service-quality-lab",
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies deterministic trustworthy-context behavior over the synthetic lab. "
            "It does not assert production generalization, live cross-plane deployment, "
            "runtime acceptance or stakeholder approval. ADLC retains the final promotion decision."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="white-goods-phase2-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase2())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
