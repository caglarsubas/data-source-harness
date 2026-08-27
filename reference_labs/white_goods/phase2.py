"""Phase-2 trustworthy-context composition for the white-goods lab."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta

from data_source_harness.connector import Capability, ConnectorProfile, DataModel, RuntimeMode
from data_source_harness.context import ContextEnvelope, ContextOutcome
from data_source_harness.coverage import CoverageExclusion, CoverageStatement
from data_source_harness.freshness import (
    CheckpointLedger,
    FreshnessObservation,
    FreshnessRegistry,
    FreshnessSLO,
)
from data_source_harness.governance import (
    MappingReview,
    MappingStatus,
    SemanticMappingCandidate,
    SemanticMappingRegistry,
)
from data_source_harness.models import (
    BatchKind,
    CheckpointToken,
    DataBatch,
    FieldSchema,
    LineageRef,
    QueryRequest,
)
from data_source_harness.planning import (
    BoundedQueryPlan,
    BoundedQueryPlanner,
    PlanningConstraints,
    QueryIntent,
    RelationshipRef,
)
from data_source_harness.promotion import (
    CompatibilityEntry,
    CompatibilityMatrix,
    EvidenceKind,
    EvidenceStatus,
    PromotionEvidence,
    PromotionReadiness,
    PromotionReadinessEvaluator,
)
from data_source_harness.routing import (
    RouteDecision,
    RouteRequest,
    SemanticSourceRouter,
)
from data_source_harness.semantic import SemanticAssertion

from .lab import FIXED_TIME, LAB_ROOT, BaseLabConnector, WhiteGoodsLab


class SemanticGraphConnector(BaseLabConnector):
    """Sixth source family: governed semantic assertions as a graph source."""

    def __init__(self) -> None:
        super().__init__(
            ConnectorProfile(
                "whitegoods.semantic-graph",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.GRAPH}),
                frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
                frozenset({"credential_reference"}),
            ),
            {
                "semantic_assertions": (
                    FieldSchema("assertion_id", "string", False),
                    FieldSchema("subject_id", "string", False),
                    FieldSchema("predicate", "string", False),
                    FieldSchema("object_id", "string", False),
                    FieldSchema("confidence", "number", False),
                )
            },
        )

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._require_available()
        assertions: tuple[SemanticAssertion, ...] = WhiteGoodsLab.semantic_graph().active()
        rows = [
            {
                "assertion_id": item.assertion_id,
                "subject_id": item.subject_id,
                "predicate": item.predicate.value,
                "object_id": item.object_id,
                "confidence": item.confidence,
            }
            for item in assertions[: request.limit]
        ]
        lineage = tuple(value for item in assertions[: request.limit] for value in item.lineage)
        yield DataBatch(BatchKind.GRAPH, rows, (self.version,), lineage, row_count=len(rows))


def mapping_registry() -> SemanticMappingRegistry:
    document = json.loads((LAB_ROOT / "semantic-mappings.json").read_text(encoding="utf-8"))
    registry = SemanticMappingRegistry()
    for item in document["mappings"]:
        target = item["target"]
        lineage = tuple(
            LineageRef(
                value["sourceId"],
                value["assetId"],
                value.get("recordId"),
                value.get("fieldPath"),
            )
            for value in item["lineage"]
        )
        candidate = SemanticMappingCandidate(
            item["mappingId"],
            item["conceptId"],
            target["sourceId"],
            target["assetId"],
            target["fieldPath"],
            item["confidence"],
            item["schemaDigest"],
            FIXED_TIME,
            item["rationale"],
            lineage,
        )
        registry.propose(candidate)
        review = item["review"]
        registry.review(
            MappingReview(
                candidate.mapping_id,
                MappingStatus(review["status"]),
                review["reviewedBy"],
                FIXED_TIME,
                review["reason"],
            )
        )
    return registry


def freshness_registry() -> FreshnessRegistry:
    registry = FreshnessRegistry()
    document = json.loads((LAB_ROOT / "freshness-slos.json").read_text(encoding="utf-8"))
    for item in document["observations"]:
        registry.record(
            FreshnessObservation(
                item["sourceId"],
                item["assetId"],
                FIXED_TIME,
                FIXED_TIME - timedelta(seconds=item["ageSeconds"]),
                item["watermark"],
            )
        )
    return registry


def phase2_router() -> SemanticSourceRouter:
    return SemanticSourceRouter(mapping_registry(), freshness_registry())


def covered_route() -> RouteDecision:
    return phase2_router().route(
        RouteRequest(
            "phase2-e21",
            (
                "service.error-code",
                "telemetry.error-code",
                "diagnosis.guidance",
                "appointment.status",
            ),
            4,
            0.85,
            0.02,
            FreshnessSLO(timedelta(minutes=5)),
        ),
        FIXED_TIME,
    )


def ambiguous_route() -> RouteDecision:
    registry = mapping_registry()
    for mapping_id, source_id in (
        ("map-component-docs", "whitegoods.documents"),
        ("map-component-search", "whitegoods.search"),
    ):
        candidate = SemanticMappingCandidate(
            mapping_id,
            "component.failure",
            source_id,
            "technical_documents"
            if source_id.endswith("documents")
            else "technical_document_index",
            "component_name",
            0.91,
            "sha256:component-v1",
            FIXED_TIME,
            "equal evidence requires steward selection",
            (LineageRef(source_id, "technical_documents", field_path="component_name"),),
        )
        registry.propose(candidate)
        registry.review(
            MappingReview(
                mapping_id, MappingStatus.APPROVED, "human:lab-steward", FIXED_TIME, "verified"
            )
        )
    freshness = freshness_registry()
    freshness.record(
        FreshnessObservation(
            "whitegoods.documents", "technical_documents", FIXED_TIME, FIXED_TIME, "docs:4"
        )
    )
    return SemanticSourceRouter(registry, freshness).route(
        RouteRequest(
            "phase2-ambiguous",
            ("component.failure",),
            1,
            0.85,
            0.02,
            FreshnessSLO(timedelta(minutes=5)),
        ),
        FIXED_TIME,
    )


def bounded_e21_plan() -> BoundedQueryPlan:
    return BoundedQueryPlanner().compile(
        QueryIntent(
            "whitegoods.erp",
            ("service_orders", "installed_products"),
            {
                "service_orders": (
                    "service_order_id",
                    "serial_number",
                    "error_code",
                ),
                "installed_products": ("serial_number", "product_id"),
            },
            {"service_orders": {"error_code": "E21"}},
            (
                RelationshipRef(
                    "service_orders",
                    "serial_number",
                    "installed_products",
                    "serial_number",
                ),
            ),
            20,
            1_000,
            "covered E21 analysis",
        ),
        PlanningConstraints(
            {
                "service_orders": frozenset({"service_order_id", "serial_number", "error_code"}),
                "installed_products": frozenset({"serial_number", "product_id"}),
            },
            frozenset({"service_orders.serial_number->installed_products.serial_number"}),
            2,
            100,
            2_000,
        ),
    )


def checkpoint_ledger() -> CheckpointLedger:
    ledger = CheckpointLedger()
    ledger.record(
        CheckpointToken("whitegoods.telemetry", "telemetry_events", "8", FIXED_TIME, "1.0.0")
    )
    ledger.record(
        CheckpointToken("whitegoods.telemetry", "telemetry_events", "9", FIXED_TIME, "1.0.0")
    )
    return ledger


def compatibility_matrix() -> CompatibilityMatrix:
    document = json.loads(
        (LAB_ROOT.parents[1] / "compatibility/cross-plane-release-set.lock.json").read_text(
            encoding="utf-8"
        )
    )
    return CompatibilityMatrix(
        document["releaseSet"],
        tuple(
            CompatibilityEntry(
                item["name"], item["revision"], True, f"contract-pin:{item['revision']}"
            )
            for item in document["components"]
        ),
    )


def promotion_readiness(*, simulate_all_evidence: bool = False) -> PromotionReadiness:
    evidence = tuple(
        PromotionEvidence(
            f"phase2-{kind.value}",
            kind,
            (EvidenceStatus.PASSED if simulate_all_evidence else EvidenceStatus.MISSING),
            "0" * 40,
            f"sha256:phase2-{kind.value}",
        )
        for kind in EvidenceKind
    )
    return PromotionReadinessEvaluator().evaluate(evidence, compatibility_matrix())


async def grounded_e21_context() -> ContextEnvelope:
    brief, coverage = await WhiteGoodsLab().e21_cross_source_brief()
    route = covered_route()
    lineage = tuple(
        [
            LineageRef("whitegoods.erp", "service_orders", item)
            for item in brief["service_order_ids"]
        ]
        + [
            LineageRef("whitegoods.telemetry", "telemetry_events", item)
            for item in brief["telemetry_event_ids"]
        ]
        + [
            LineageRef("whitegoods.documents", "technical_documents", item)
            for item in brief["document_ids"]
        ]
        + [
            LineageRef("whitegoods.service-api", "appointments", item)
            for item in brief["appointment_ids"]
        ]
    )
    return ContextEnvelope(
        "phase2-e21",
        ContextOutcome.ANSWER,
        "E21 is grounded in service, telemetry, technical guidance and appointment evidence.",
        route,
        CoverageStatement("phase2-e21", coverage.generated_at, coverage.included),
        lineage,
    )


def ambiguous_context() -> ContextEnvelope:
    route = ambiguous_route()
    return ContextEnvelope(
        route.request_id,
        ContextOutcome.ESCALATION,
        None,
        route,
        CoverageStatement(
            route.request_id,
            FIXED_TIME,
            (),
            (
                CoverageExclusion(
                    "semantic-registry",
                    "ambiguous_mapping",
                    "human steward must choose the component mapping",
                ),
            ),
        ),
        (),
        route.reason_codes,
    )
