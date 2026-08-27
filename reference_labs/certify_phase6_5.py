"""Phase-6.5 integration-spine and trust-boundary certification."""

from __future__ import annotations

import argparse
import asyncio
import json
import zipfile
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import jsonschema

from data_source_harness import __version__
from data_source_harness.actions import HmacApprovalAuthority
from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    ConnectorRegistry,
    DataModel,
    RuntimeMode,
)
from data_source_harness.coordination import (
    CoordinationResult,
    CrossSourceCoordinator,
    QueryStep,
    SourceExecutionPlan,
)
from data_source_harness.cross_plane import CrossPlaneEvidenceBridge, GovernedModelPlane
from data_source_harness.delegation import A2AActionDelegationAdapter, DelegationRejected
from data_source_harness.models import QueryRequest
from data_source_harness.policy import RequestIdentity, StaticPolicy
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink
from data_source_harness.worker import ConnectorWorkerClient
from data_source_harness.worker_connector import WorkerBackedConnector
from reference_labs.white_goods.certify import CertificationCheck, MetricResult, _metric
from reference_labs.white_goods.lab import FIXED_TIME, WhiteGoodsLab
from reference_labs.white_goods.phase2 import execute_bounded_e21_plan
from reference_labs.white_goods.phase4 import service_action
from reference_labs.white_goods.runtime_bundle import (
    DEFAULT_OUTPUT,
    build_runtime_bundle,
    readiness,
)

from .certify_phase6 import _worker_spec, certify_phase6

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GQM_PATH = Path(__file__).resolve().with_name("phase6_5_gqm_plan.json")


@dataclass(frozen=True)
class Phase65Report:
    phase: str
    lab_id: str
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _SdkSink:
    def __init__(self) -> None:
        self.evidence: dict[str, Any] | None = None

    async def publish_execution_evidence(self, evidence: dict[str, Any]) -> str:
        self.evidence = dict(evidence)
        return "sdk:execution:phase6.5"


class _AdlcSink:
    def __init__(self) -> None:
        self.evidence: dict[str, Any] | None = None

    async def ingest_runtime_evidence(self, evidence: dict[str, Any]) -> str:
        self.evidence = dict(evidence)
        return "adlc:evidence:phase6.5"


class _ModelClient:
    def __init__(self) -> None:
        self.tenant: dict[str, str] | None = None

    async def rerank(
        self,
        *,
        request_id: str,
        query: str,
        candidates: tuple[str, ...],
        tenant: dict[str, str],
    ) -> tuple[float, ...]:
        self.tenant = dict(tenant)
        return tuple(float(len(value)) for value in candidates)


def _identity(request_id: str = "phase6.5-worker") -> RequestIdentity:
    return RequestIdentity(
        "org-lab",
        "whitegoods-lab",
        "agent-quality",
        request_id,
        f"trace:{request_id}",
        "policy:wg-v1",
    )


def _worker_profile(connector_id: str = "whitegoods.reference-worker") -> ConnectorProfile:
    return ConnectorProfile(
        connector_id,
        __version__,
        "harness.connector/v1",
        RuntimeMode.PROCESS,
        frozenset({DataModel.TABULAR}),
        frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
        frozenset({"credential_reference"}),
        limits=ConnectorLimits(max_parallelism=2, max_result_bytes=1024 * 1024),
    )


async def _worker_execution() -> tuple[bool, CoordinationResult, str]:
    connector = WorkerBackedConnector(
        _worker_profile(),
        ConnectorWorkerClient(_worker_spec()),
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("whitegoods.reference-worker", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    request_id = "phase6.5-worker"
    result = await CrossSourceCoordinator(gateway).execute(
        SourceExecutionPlan(
            request_id,
            FIXED_TIME,
            (
                QueryStep(
                    "worker-service-orders",
                    QueryRequest(
                        "whitegoods.reference-worker",
                        ("service_orders",),
                        {
                            "where_by_asset": {"service_orders": {"error_code": "E21"}},
                            "select_by_asset": {
                                "service_orders": [
                                    "service_order_id",
                                    "serial_number",
                                    "error_code",
                                ]
                            },
                        },
                        20,
                        1_000,
                        "Phase 6.5 worker integration",
                    ),
                ),
            ),
        ),
        _identity(request_id),
    )
    batches = result.step("worker-service-orders").batches
    passed = (
        result.complete
        and result.coverage.expected_sources == frozenset({"whitegoods.reference-worker"})
        and len(batches) == 1
        and batches[0].row_count == 2
        and {row["error_code"] for row in batches[0].payload} == {"E21"}
        and all(item.source_id == "whitegoods.reference-worker" for item in result.lineage)
    )
    return passed, result, f"batches={len(batches)}; lineage={len(result.lineage)}"


async def _pilot_execution() -> tuple[bool, bool, str]:
    batches = await execute_bounded_e21_plan()
    bounded = (
        len(batches) == 2
        and {item.asset_id for batch in batches for item in batch.lineage}
        == {"service_orders", "installed_products"}
        and {row["error_code"] for row in batches[0].payload} == {"E21"}
    )
    brief, coverage = await WhiteGoodsLab().e21_cross_source_brief()
    four_source = (
        coverage.is_complete
        and coverage.expected_sources
        == frozenset(
            {
                "whitegoods.erp",
                "whitegoods.telemetry",
                "whitegoods.search",
                "whitegoods.service-api",
            }
        )
        and brief["lineage_count"] >= 7
    )
    return (
        bounded,
        four_source,
        f"bounded_batches={len(batches)}; sources={len(coverage.expected_sources)}; "
        f"lineage={brief['lineage_count']}",
    )


def _trust_boundaries() -> tuple[int, str]:
    false_accepts = 0
    action = service_action()
    identity = _identity("phase6.5-approval")
    authority = HmacApprovalAuthority(
        "adlc-phase6.5",
        "data-source-harness",
        b"phase6.5-offline-approval-authority",
    )
    approval = authority.issue(
        action_digest=action.digest,
        approver_id="human:service-manager",
        policy_digest=identity.policy_digest,
        approved_at=FIXED_TIME - timedelta(minutes=1),
        expires_at=FIXED_TIME + timedelta(minutes=10),
        allow_compensation=True,
        identity=identity,
        nonce="phase6.5-approval",
    )
    false_accepts += int(
        not authority.verify(approval, action, identity, FIXED_TIME, compensation=False)
    )
    forged = replace(approval, approval_id="human:service-manager:forged")
    false_accepts += int(authority.verify(forged, action, identity, FIXED_TIME, compensation=False))
    other_identity = replace(identity, request_id="other-request")
    false_accepts += int(
        authority.verify(approval, action, other_identity, FIXED_TIME, compensation=False)
    )

    malformed = {
        "protocol": "a2a/1.0",
        "taskId": "phase6.5-malformed",
        "requestingAgent": identity.agent_id,
        "sourceAction": {
            "actionId": action.action_id,
            "sourceId": action.source_id,
            "assetId": action.asset_id,
            "operation": action.operation,
            "parameters": dict(action.parameters),
            "preconditions": dict(action.preconditions),
            "idempotencyKey": action.idempotency_key,
            "risk": action.risk.value,
            "approvalMode": action.approval_mode.value,
            "purpose": action.purpose,
            "compensation": {"operation": "restore", "parameters": {}, "extra": True},
        },
    }
    try:
        A2AActionDelegationAdapter(
            frozenset({(action.source_id, action.operation)})
        ).to_action_plan(malformed, identity)
    except DelegationRejected:
        pass
    else:
        false_accepts += 1

    try:
        replace(_worker_spec(), image_digest="sha256:" + "a" * 64)
    except ValueError:
        pass
    else:
        false_accepts += 1
    return false_accepts, "signed approval, tenant binding, exact delegation and runtime claim"


async def _cross_plane_execution(result: CoordinationResult) -> tuple[bool, str]:
    sdk = _SdkSink()
    adlc = _AdlcSink()
    identity = _identity(result.request_id)
    receipt = await CrossPlaneEvidenceBridge(sdk, adlc).publish(result, identity)
    model = _ModelClient()
    ranking = await GovernedModelPlane(model, max_candidates=3).rerank(
        "E21 diagnosis",
        ("short", "longer", "longest"),
        identity,
    )
    expected_tenant = {
        "organizationId": identity.organization_id,
        "solutionId": identity.solution_id,
        "agentId": identity.agent_id,
    }
    passed = (
        sdk.evidence is not None
        and adlc.evidence is not None
        and "payload" not in sdk.evidence
        and adlc.evidence["sdkReceiptId"] == receipt.sdk_receipt_id
        and model.tenant == expected_tenant
        and ranking == (2, 1, 0)
    )
    return passed, f"sdk={receipt.sdk_receipt_id}; adlc={receipt.adlc_evidence_id}"


def _acceptance_packet() -> tuple[bool, bool, str]:
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/cross-plane-evidence-set.schema.json").read_text()
    )
    evidence = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase6.5-cross-plane-evidence.json").read_text()
    )
    release_set = json.loads(
        (REPOSITORY_ROOT / "compatibility/cross-plane-release-set.lock.json").read_text()
    )
    evidence_valid = jsonschema.Draft202012Validator(schema).is_valid(evidence)
    locked = {
        (item["name"], item["repository"], item["revision"]) for item in release_set["components"]
    }
    evidenced = {
        (item["component"], item["repository"], item["revision"]) for item in evidence["components"]
    }
    no_false_acceptance = evidence["combinedRuntimeAccepted"] is False and all(
        component["evidence"][state]["status"] == "missing"
        for component in evidence["components"]
        for state in (
            "ci",
            "published",
            "deployed",
            "runtimeVerified",
            "faultVerified",
            "stakeholderAccepted",
        )
    )
    build_runtime_bundle(DEFAULT_OUTPUT)
    status = readiness(DEFAULT_OUTPUT)
    with zipfile.ZipFile(DEFAULT_OUTPUT) as archive:
        names = set(archive.namelist())
    required = {
        "runtime/Containerfile",
        "runtime/wheelhouse-requirements.txt",
        "runtime/mirroring/imageset-config.template.yaml",
        "runtime/openshift/config-map.yaml",
        "runtime/openshift/deployment.template.yaml",
        "runtime/openshift/network-policy-allow-internal.yaml",
        "runtime/openshift/network-policy.yaml",
        "runtime/openshift/service.yaml",
        "compatibility/phase6.5-cross-plane-evidence.json",
    }
    if status["wheelhouseComplete"]:
        required.add("wheels/wheelhouse-manifest.json")
    packet_valid = (
        status["artifactIntegrity"] is True
        and required <= names
        and "image-digests-unresolved" in status["blockers"]
        and status["mirrorVerified"] is False
        and status["deployed"] is False
        and status["zeroEgressRuntimeVerified"] is False
        and status["stakeholderAccepted"] is False
    )
    return (
        evidence_valid and locked == evidenced and packet_valid,
        no_false_acceptance,
        f"planes={len(evidenced)}; bundle_entries={len(names)}; "
        f"wheelhouse={status['wheelhouseComplete']}; blockers={len(status['blockers'])}",
    )


async def certify_phase6_5() -> Phase65Report:
    phase6 = await certify_phase6()
    bounded, four_source, pilot_detail = await _pilot_execution()
    worker_valid, worker_result, worker_detail = await _worker_execution()
    false_accepts, trust_detail = _trust_boundaries()
    cross_plane, cross_plane_detail = await _cross_plane_execution(worker_result)
    evidence_valid, no_false_acceptance, packet_detail = _acceptance_packet()
    checks = [
        CertificationCheck("regression.phase6", phase6.passed, "Phase-6 certificate rerun"),
        CertificationCheck("planner.pilot-end-to-end", bounded, pilot_detail),
        CertificationCheck("coordination.four-source-coverage-lineage", four_source, pilot_detail),
        CertificationCheck("worker.canonical-connector-abi", worker_valid, worker_detail),
        CertificationCheck("trust.false-acceptance-denial", false_accepts == 0, trust_detail),
        CertificationCheck(
            "compatibility.four-plane-pinned-evidence",
            evidence_valid and no_false_acceptance,
            packet_detail,
        ),
        CertificationCheck("cross-plane.tenant-neutral-seams", cross_plane, cross_plane_detail),
    ]
    plan = json.loads(GQM_PATH.read_text())
    definitions = {item["metricId"]: item for item in plan["metrics"]}
    metrics = (
        _metric(definitions, "P65-M1", float(bounded), pilot_detail),
        _metric(definitions, "P65-M2", float(four_source), pilot_detail),
        _metric(definitions, "P65-M3", float(worker_valid), worker_detail),
        _metric(definitions, "P65-M4", float(false_accepts), trust_detail),
        _metric(definitions, "P65-M5", float(evidence_valid), packet_detail),
        _metric(definitions, "P65-M6", float(cross_plane), cross_plane_detail),
        _metric(
            definitions,
            "P65-M7",
            float(not no_false_acceptance),
            "combined runtime remains unaccepted",
        ),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase6.5-plan-complete",
            {item["metricId"] for item in plan["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(plan['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = all(check.passed for check in checks) and all(metric.passed for metric in metrics)
    return Phase65Report(
        "phase-6.5",
        "white-goods-integration-spine",
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies deterministic local pilot execution, the canonical gateway-to-process "
            "connector ABI, explicit four-source coverage and lineage, signed approval trust, "
            "tenant-neutral SDK/ADLC/model-plane seams, exact four-plane pins, and a signed "
            "disconnected transfer packet. It does not claim upstream repository CI, published "
            "artifacts, real PostgreSQL/S3/Kafka/REST integrations, a built or mirrored container "
            "image, live OpenShift deployment, zero-egress runtime proof, fault verification, "
            "production generalization or stakeholder acceptance."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase6.5-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase6_5())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
