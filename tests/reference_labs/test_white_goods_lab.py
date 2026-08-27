from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_source_harness.conformance import run_connector_conformance
from data_source_harness.decoder import ContentTrust, DecodeRequest, PayloadFormat
from data_source_harness.models import LineageRef, QueryRequest, SearchRequest
from data_source_harness.policy import PolicyDenied
from reference_labs.white_goods.bundle import build_bundle, verify_bundle
from reference_labs.white_goods.certify import certify
from reference_labs.white_goods.lab import LAB_ROOT, WhiteGoodsLab, dataset_digest


def test_seed_is_deterministic_and_manifested() -> None:
    lab = WhiteGoodsLab()
    before = lab.erp.snapshot_digest()
    lab.erp.rows["products"].append(dict(lab.erp.rows["products"][0]))
    assert lab.erp.snapshot_digest() != before
    lab.reset()
    assert lab.erp.snapshot_digest() == before
    lock = json.loads((LAB_ROOT / "dataset.lock.json").read_text(encoding="utf-8"))
    assert dataset_digest() == lock["sha256"]


def test_offline_bundle_is_reproducible_and_self_verifying(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    wheel = tmp_path / "orchestra_data_source_harness-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"deterministic wheel fixture")
    first_digest = build_bundle(first, wheel)
    second_digest = build_bundle(second, wheel)
    assert first_digest == second_digest
    assert verify_bundle(first) == first_digest


@pytest.mark.asyncio
async def test_all_five_source_families_pass_connector_conformance() -> None:
    lab = WhiteGoodsLab()
    reports = [await run_connector_conformance(connector) for connector in lab.connectors]
    assert len(reports) == 5
    assert all(report.passed for report in reports), reports


@pytest.mark.asyncio
async def test_cross_customer_query_is_denied_before_data_emission() -> None:
    lab = WhiteGoodsLab()
    request = QueryRequest(
        "whitegoods.erp",
        ("service_orders",),
        {"where": {"customer_id": "C002"}},
        10,
        1_000,
        "customer service history",
        {"customer_id": "C002"},
    )
    with pytest.raises(PolicyDenied, match="customer_scope_denied"):
        _ = [
            batch
            async for batch in lab.gateway.execute(
                request, lab.identity("agent-service-c001", "cross-customer")
            )
        ]
    assert all(event.name != "data.harness.batch.emitted" for event in lab.telemetry.events)


@pytest.mark.asyncio
async def test_policy_scope_cannot_be_spoofed_independently_of_query_plan() -> None:
    lab = WhiteGoodsLab()
    request = QueryRequest(
        "whitegoods.erp",
        ("service_orders",),
        {"where": {"customer_id": "C002"}},
        10,
        1_000,
        "customer service history",
        {"customer_id": "C001"},
    )
    with pytest.raises(PolicyDenied, match="scope_attribute_mismatch"):
        _ = [
            batch
            async for batch in lab.gateway.execute(
                request, lab.identity("agent-service-c001", "spoofed-scope")
            )
        ]


@pytest.mark.asyncio
async def test_checkpoint_replay_deduplicates_and_retains_late_event() -> None:
    lab = WhiteGoodsLab()
    replayed = [event async for event in lab.events.subscribe("4")]
    assert [event.event_id for event in replayed] == ["EV005", "EV006", "EV007"]
    assert any(event.payload.get("late") for event in replayed)


@pytest.mark.asyncio
async def test_search_is_acl_filtered_and_preserves_lineage() -> None:
    lab = WhiteGoodsLab()
    request = SearchRequest(
        "whitegoods.search",
        "repeat E21 pump revision lot",
        3,
        {"role": "quality"},
        "guided service retrieval",
        {"role": "quality"},
    )
    hits = await lab.gateway.search(request, lab.identity("agent-quality", "retrieval"))
    assert hits[0].record_id == "DOC-WM-PUMP-2025-02"
    assert all(hit.lineage for hit in hits)


@pytest.mark.asyncio
async def test_adversarial_document_remains_untrusted_data() -> None:
    lab = WhiteGoodsLab()
    request = QueryRequest(
        "whitegoods.documents",
        ("technical_documents",),
        {"role": "service"},
        20,
        1_000,
        "inspect service evidence",
        {"role": "service"},
    )
    batches = [
        batch
        async for batch in lab.gateway.execute(
            request, lab.identity("agent-service-c001", "prompt-injection")
        )
    ]
    hostile = next(item for item in batches[0].payload if item["document_id"] == "DOC-UNTRUSTED-01")
    assert "Ignore previous instructions" in hostile["content"]
    assert hostile["trust"] == "untrusted-source"
    path = LAB_ROOT / "data/documents/untrusted-field-note.md"
    decoded = await lab.decoder_registry.get(PayloadFormat.TEXT).decode(
        DecodeRequest(
            path.read_bytes(),
            PayloadFormat.TEXT,
            lab.documents.version,
            (LineageRef("whitegoods.documents", "technical_documents", hostile["document_id"]),),
            "text/markdown",
        )
    )
    assert decoded.trust is ContentTrust.UNTRUSTED_SOURCE
    assert decoded.batches[0].lineage


@pytest.mark.asyncio
async def test_known_cross_source_answer_is_grounded() -> None:
    lab = WhiteGoodsLab()
    assert await lab.repeat_visit_model() == "WG-WM-500"
    cluster = lab.semantic_graph().equivalence_cluster("term:drainage-motor")
    assert cluster == frozenset({"term:drainage-motor", "part:drain-pump"})


@pytest.mark.asyncio
async def test_e21_brief_integrates_four_sources_with_complete_coverage() -> None:
    brief, coverage = await WhiteGoodsLab().e21_cross_source_brief()
    assert brief["service_order_ids"] == ["SO1001", "SO1002"]
    assert brief["telemetry_event_ids"] == ["EV001", "EV003"]
    assert "DOC-WM-E21" in brief["document_ids"]
    assert brief["appointment_ids"] == ["AP001"]
    assert brief["lineage_count"] >= 8
    assert coverage.is_complete
    assert len(coverage.included) == 4


@pytest.mark.asyncio
async def test_service_api_fixture_exercises_pagination() -> None:
    lab = WhiteGoodsLab()
    request = QueryRequest(
        "whitegoods.service-api",
        ("appointments",),
        {"page_size": 2},
        10,
        1_000,
        "pagination conformance",
    )
    batches = [
        batch
        async for batch in lab.gateway.execute(
            request, lab.identity("agent-quality", "api-pagination")
        )
    ]
    assert [batch.row_count for batch in batches] == [2, 1]
    assert len({row["appointment_id"] for batch in batches for row in batch.payload}) == 3


@pytest.mark.asyncio
async def test_phase1_certification_report_passes_every_gqm_threshold() -> None:
    report = await certify()
    assert report.passed, report
    assert all(check.passed for check in report.checks)
    assert all(metric.passed for metric in report.metrics)
    gqm = json.loads((LAB_ROOT / "gqm-plan.json").read_text(encoding="utf-8"))
    assert {item["metricId"] for item in gqm["metrics"]} == {
        metric.metric_id for metric in report.metrics
    }
