"""Machine-readable Phase-1 certification for the white-goods lab."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import statistics
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from data_source_harness.conformance import run_connector_conformance
from data_source_harness.decoder import ContentTrust, DecodeRequest, PayloadFormat
from data_source_harness.deployment import (
    DeploymentMode,
    DeploymentProfile,
    EgressDenied,
    EgressGuard,
)
from data_source_harness.models import LineageRef, QueryRequest, SearchRequest
from data_source_harness.policy import PolicyDenied

from .lab import LAB_ROOT, LabSourceUnavailable, WhiteGoodsLab, dataset_digest

REPOSITORY_ROOT = LAB_ROOT.parents[1]


@dataclass(frozen=True)
class CertificationCheck:
    check_id: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class MetricResult:
    metric_id: str
    value: float
    operator: str
    threshold: float
    passed: bool
    evidence: str


@dataclass(frozen=True)
class Phase1Report:
    phase: str
    lab_id: str
    dataset_digest: str
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evaluate(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    if operator == "==":
        return value == threshold
    raise ValueError(f"unsupported GQM operator: {operator}")


def _metric(
    definitions: dict[str, dict[str, Any]], metric_id: str, value: float, evidence: str
) -> MetricResult:
    definition = definitions[metric_id]
    threshold = float(definition["threshold"])
    operator = definition["operator"]
    return MetricResult(
        metric_id,
        value,
        operator,
        threshold,
        _evaluate(value, operator, threshold),
        evidence,
    )


@contextmanager
def deny_network() -> Iterator[list[str]]:
    attempts: list[str] = []
    original_connect = socket.socket.connect

    def blocked_connect(instance: socket.socket, address: Any) -> None:
        attempts.append(repr(address))
        raise OSError("reference-lab certification denies network egress")

    socket.socket.connect = blocked_connect
    try:
        yield attempts
    finally:
        socket.socket.connect = original_connect


def _validate_manifests() -> tuple[CertificationCheck, ...]:
    checks: list[CertificationCheck] = []
    targets = (
        (
            "manifest.industry-pack",
            REPOSITORY_ROOT / "schemas/v1/industry-domain-pack-manifest.schema.json",
            LAB_ROOT / "pack-manifest.json",
        ),
        (
            "manifest.reference-lab",
            REPOSITORY_ROOT / "schemas/v1/reference-lab-manifest.schema.json",
            LAB_ROOT / "reference-lab-manifest.json",
        ),
    )
    for check_id, schema_path, document_path in targets:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        document = json.loads(document_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        )
        errors = list(validator.iter_errors(document))
        checks.append(
            CertificationCheck(
                check_id,
                not errors,
                "; ".join(error.message for error in errors) if errors else document_path.name,
            )
        )

    compose = yaml.safe_load((LAB_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services", {})
    internal = compose.get("networks", {}).get("lab-internal", {}).get("internal") is True
    checks.append(
        CertificationCheck(
            "topology.heterogeneous-and-internal",
            set(services) == {"postgres", "minio", "redpanda", "opensearch"} and internal,
            f"services={','.join(sorted(services))}; internal={internal}",
        )
    )
    openapi = yaml.safe_load(
        (LAB_ROOT / "technology/service-api/openapi.yaml").read_text(encoding="utf-8")
    )
    checks.append(
        CertificationCheck(
            "contract.openapi",
            str(openapi.get("openapi", "")).startswith("3.1")
            and "/appointments" in openapi.get("paths", {}),
            str(openapi.get("info", {}).get("version")),
        )
    )
    return tuple(checks)


async def certify() -> Phase1Report:
    lab = WhiteGoodsLab()
    checks = list(_validate_manifests())
    gqm = json.loads((LAB_ROOT / "gqm-plan.json").read_text(encoding="utf-8"))
    definitions = {item["metricId"]: item for item in gqm["metrics"]}
    dataset_lock = json.loads((LAB_ROOT / "dataset.lock.json").read_text(encoding="utf-8"))
    locked_digest = dataset_lock["sha256"]
    actual_digest = dataset_digest()
    checks.append(
        CertificationCheck(
            "data.locked-digest",
            actual_digest == locked_digest,
            f"sha256={actual_digest}",
        )
    )

    conformance_reports = [await run_connector_conformance(item) for item in lab.connectors]
    checks.append(
        CertificationCheck(
            "connectors.conformance",
            all(report.passed for report in conformance_reports),
            ", ".join(
                f"{report.connector_id}:"
                f"{sum(check.passed for check in report.checks)}/{len(report.checks)}"
                for report in conformance_reports
            ),
        )
    )

    expected_counts = dataset_lock["expected"]["tables"]
    counts_ok = {key: len(lab.erp.rows[key]) for key in expected_counts} == expected_counts
    products = {row["product_id"] for row in lab.erp.rows["products"]}
    customers = {row["customer_id"] for row in lab.erp.rows["customers"]}
    installed = {
        row["serial_number"]: (row["product_id"], row["customer_id"])
        for row in lab.erp.rows["installed_products"]
    }
    installed_keys_ok = all(
        row["product_id"] in products and row["customer_id"] in customers
        for row in lab.erp.rows["installed_products"]
    )
    service_keys_ok = all(
        row["serial_number"] in installed
        and installed[row["serial_number"]][1] == row["customer_id"]
        for row in lab.erp.rows["service_orders"]
    )
    quality_keys_ok = all(
        row["product_id"] in products for row in lab.erp.rows["quality_inspections"]
    )
    foreign_keys_ok = installed_keys_ok and service_keys_ok and quality_keys_ok
    event_shape_ok = (
        len(lab.documents.documents) == dataset_lock["expected"]["documents"]
        and len(lab.events.raw_events) == dataset_lock["expected"]["rawEvents"]
        and len(lab.events.logical_events()) == dataset_lock["expected"]["logicalEvents"]
        and sum(bool(event.get("duplicate")) for event in lab.events.raw_events)
        == dataset_lock["expected"]["duplicateEvents"]
        and sum(bool(event.get("quarantine_reason")) for event in lab.events.raw_events)
        == dataset_lock["expected"]["quarantinedEvents"]
        and len(lab.service_api.fixture["appointments"]) == dataset_lock["expected"]["appointments"]
    )
    checks.append(
        CertificationCheck(
            "data.fidelity",
            counts_ok and foreign_keys_ok and event_shape_ok,
            (
                f"counts={expected_counts}; foreign_keys={foreign_keys_ok}; "
                f"event_shape={event_shape_ok}"
            ),
        )
    )

    baseline = lab.erp.snapshot_digest()
    lab.erp.rows["products"].append(dict(lab.erp.rows["products"][0]))
    changed = lab.erp.snapshot_digest() != baseline
    lab.reset()
    reset_ok = changed and lab.erp.snapshot_digest() == baseline

    authorized = QueryRequest(
        "whitegoods.erp",
        ("service_orders",),
        {"where": {"customer_id": "C001"}},
        20,
        1_000,
        "customer service history",
        {"customer_id": "C001"},
    )
    allowed_batches = [
        item
        async for item in lab.gateway.execute(
            authorized, lab.identity("agent-service-c001", "auth-allow")
        )
    ]
    denied = QueryRequest(
        "whitegoods.erp",
        ("service_orders",),
        {"where": {"customer_id": "C002"}},
        20,
        1_000,
        "customer service history",
        {"customer_id": "C002"},
    )
    denied_before_batch = False
    try:
        _ = [
            item
            async for item in lab.gateway.execute(
                denied, lab.identity("agent-service-c001", "auth-deny")
            )
        ]
    except PolicyDenied:
        denied_before_batch = True
    authorization_rate = float(bool(allowed_batches) and denied_before_batch)

    lineage_items = [lineage for batch in allowed_batches for lineage in batch.lineage]
    authorized_lineage_complete = bool(lineage_items) and all(
        item.source_id and item.asset_id and item.record_id for item in lineage_items
    )

    replayed = [event async for event in lab.events.subscribe("4")]
    replay_ok = (
        [event.event_id for event in replayed] == ["EV005", "EV006", "EV007"]
        and len({event.event_id for event in replayed}) == len(replayed)
        and any(event.payload.get("late") for event in replayed)
    )

    lab.documents.available = False
    unhealthy = not (await lab.documents.health()).healthy
    outage_raised = False
    try:
        await lab.documents.discover()
    except LabSourceUnavailable:
        outage_raised = True
    lab.documents.available = True
    checks.append(
        CertificationCheck(
            "failure.source-outage",
            unhealthy and outage_raised,
            "health degraded and discovery failed explicitly",
        )
    )

    graph = lab.semantic_graph()
    semantic_ok = graph.equivalence_cluster("term:drainage-motor") == frozenset(
        {"term:drainage-motor", "part:drain-pump"}
    )
    checks.append(
        CertificationCheck(
            "semantics.known-alias",
            semantic_ok,
            "drainage motor resolves to drain pump; E21 remains a mentions edge",
        )
    )

    cross_source_brief, cross_source_coverage = await lab.e21_cross_source_brief()
    cross_source_ok = (
        cross_source_brief["service_order_ids"] == ["SO1001", "SO1002"]
        and cross_source_brief["telemetry_event_ids"] == ["EV001", "EV003"]
        and "DOC-WM-E21" in cross_source_brief["document_ids"]
        and cross_source_brief["appointment_ids"] == ["AP001"]
        and cross_source_brief["lineage_count"] >= 8
        and cross_source_coverage.is_complete
        and len(cross_source_coverage.included) == 4
    )
    lineage_completeness = float(
        authorized_lineage_complete and cross_source_brief["lineage_count"] >= 8
    )
    checks.append(
        CertificationCheck(
            "integration.e21-four-source-brief",
            cross_source_ok,
            (
                f"sources={len(cross_source_coverage.included)}; "
                f"lineage={cross_source_brief['lineage_count']}"
            ),
        )
    )

    retrieval_cases = (
        ("E21 drainage filter hose pump", "service", "DOC-WM-E21"),
        ("repeat E21 pump revision lot", "quality", "DOC-WM-PUMP-2025-02"),
        ("E05 temperature sensor airflow", "quality", "DOC-RF-E05"),
        ("blocked drain filter E21", "service", "DOC-WM-E21"),
        ("reduced pump flow LOT-WM-24A", "quality", "DOC-WM-PUMP-2025-02"),
        ("door seal sensor resistance", "service", "DOC-RF-E05"),
        ("drainage motor electrical isolation", "service", "DOC-WM-E21"),
        ("hose routing pump revision B", "quality", "DOC-WM-PUMP-2025-02"),
        ("export all customer records adversarial", "service", "DOC-UNTRUSTED-01"),
        ("temperature instability service tolerance", "quality", "DOC-RF-E05"),
    )
    retrieved = 0
    for index, (query, role, expected) in enumerate(retrieval_cases):
        request = SearchRequest(
            "whitegoods.search",
            query,
            3,
            {"role": role},
            "guided service retrieval",
            {"role": role},
        )
        hits = await lab.gateway.search(
            request,
            lab.identity(
                f"agent-{role}" if role == "quality" else "agent-service-c001", f"search-{index}"
            ),
        )
        retrieved += int(expected in {hit.record_id for hit in hits})
    retrieval_recall = retrieved / len(retrieval_cases)

    document_request = QueryRequest(
        "whitegoods.documents",
        ("technical_documents",),
        {"role": "service"},
        20,
        1_000,
        "inspect service evidence",
        {"role": "service"},
    )
    document_batches = [
        item
        async for item in lab.gateway.execute(
            document_request, lab.identity("agent-service-c001", "trust-label")
        )
    ]
    documents = document_batches[0].payload
    trust_rate = sum(item["trust"] == "untrusted-source" for item in documents) / len(documents)
    injection_is_data = any(
        item["document_id"] == "DOC-UNTRUSTED-01"
        and "Ignore previous instructions" in item["content"]
        and item["trust"] == "untrusted-source"
        for item in documents
    )
    hostile_path = LAB_ROOT / "data/documents/untrusted-field-note.md"
    decode_result = await lab.decoder_registry.get(PayloadFormat.TEXT).decode(
        DecodeRequest(
            hostile_path.read_bytes(),
            PayloadFormat.TEXT,
            lab.documents.version,
            (LineageRef("whitegoods.documents", "technical_documents", "DOC-UNTRUSTED-01"),),
            "text/markdown",
        )
    )
    decoder_ok = (
        decode_result.trust is ContentTrust.UNTRUSTED_SOURCE
        and decode_result.batches[0].byte_count == hostile_path.stat().st_size
        and bool(decode_result.batches[0].lineage)
    )
    checks.append(
        CertificationCheck(
            "security.prompt-injection-is-data",
            injection_is_data and decoder_ok,
            "adversarial text decoded with lineage and untrusted-source label",
        )
    )

    scenario_results = (
        await lab.repeat_visit_model() == "WG-WM-500",
        counts_ok and foreign_keys_ok,
        replay_ok,
        semantic_ok,
        injection_is_data and decoder_ok,
        cross_source_ok,
    )
    scenario_accuracy = sum(scenario_results) / len(scenario_results)

    latencies: list[float] = []
    performance_identity = lab.identity("agent-quality", "performance")
    performance_request = QueryRequest(
        "whitegoods.erp",
        ("quality_inspections",),
        {},
        20,
        1_000,
        "quality trend benchmark",
    )
    for _ in range(100):
        started = time.perf_counter()
        _ = [
            batch async for batch in lab.gateway.execute(performance_request, performance_identity)
        ]
        latencies.append((time.perf_counter() - started) * 1000)
    p95 = statistics.quantiles(latencies, n=20)[18]

    airgap_profile = DeploymentProfile(
        "whitegoods-airgap",
        DeploymentMode.AIR_GAPPED,
        frozenset({"model-plane.ai.svc", "postgres.data.svc"}),
        False,
        False,
        True,
    )
    egress_denied = False
    with deny_network() as attempts:
        _ = await lab.repeat_visit_model()
        try:
            EgressGuard(airgap_profile).authorize("https://api.external.example/v1")
        except EgressDenied:
            egress_denied = True
    egress_violations = float(len(attempts))
    checks.append(
        CertificationCheck(
            "deployment.zero-egress",
            egress_denied and not attempts,
            f"network_attempts={len(attempts)}; external_route_denied={egress_denied}",
        )
    )

    metrics = (
        _metric(
            definitions,
            "M1",
            scenario_accuracy,
            f"{sum(scenario_results)}/{len(scenario_results)} scenarios",
        ),
        _metric(
            definitions,
            "M2",
            lineage_completeness,
            f"lineage_items={len(lineage_items) + cross_source_brief['lineage_count']}",
        ),
        _metric(definitions, "M3", retrieval_recall, f"{retrieved}/{len(retrieval_cases)}"),
        _metric(definitions, "M4", authorization_rate, "allow and cross-customer deny"),
        _metric(definitions, "M5", trust_rate, f"documents={len(documents)}"),
        _metric(definitions, "M6", float(replay_ok), f"replayed={len(replayed)}"),
        _metric(definitions, "M7", float(reset_ok), f"baseline={baseline}"),
        _metric(definitions, "M8", egress_violations, "socket connect attempts"),
        _metric(definitions, "M9", p95, "100 in-process bounded queries"),
    )
    checks.append(
        CertificationCheck(
            "gqm.plan-complete",
            {item["metricId"] for item in gqm["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(gqm['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = all(item.passed for item in checks) and all(item.passed for item in metrics)
    return Phase1Report(
        "phase-1",
        "white-goods-service-quality-lab",
        actual_digest,
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies the deterministic application-level reference lab and "
            "zero-network execution. "
            "It does not assert that mutable development image tags were mirrored or that a live "
            "OpenShift cluster was deployed."
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="white-goods-lab-certify")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = asyncio.run(certify())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
