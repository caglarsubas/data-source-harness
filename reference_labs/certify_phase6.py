"""Phase-6 connector-worker, protocol-profile and acceptance-packet certification."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from data_source_harness import __version__
from data_source_harness.delegation import A2AActionDelegationAdapter
from data_source_harness.policy import RequestIdentity
from data_source_harness.protocol import (
    NorthboundActionAdapter,
    NorthboundTool,
    NorthboundToolCatalog,
)
from data_source_harness.protocol_profiles import (
    A2A_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    A2A10ActionServer,
    A2AAgentCard,
    A2AAgentSkill,
    Mcp20260728ActionServer,
)
from data_source_harness.worker import (
    ConnectorWorkerClient,
    ConnectorWorkerSpec,
    WorkerCrashed,
    WorkerLimits,
    WorkerProtocolViolation,
    WorkerTimeout,
)
from reference_labs.white_goods.certify import CertificationCheck, MetricResult, _metric
from reference_labs.white_goods.phase4 import service_action
from reference_labs.white_goods.runtime_bundle import (
    DEFAULT_OUTPUT,
    build_runtime_bundle,
    readiness,
)

from .certify_phase5 import certify_phase5

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = REPOSITORY_ROOT / "reference_labs/white_goods"
GQM_PATH = Path(__file__).resolve().with_name("phase6-gqm-plan.json")


@dataclass(frozen=True)
class Phase6Report:
    phase: str
    lab_id: str
    passed: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _identity(agent: str = "agent.whitegoods-service") -> RequestIdentity:
    return RequestIdentity(
        "org-lab", "whitegoods-lab", agent, "p6-request", "p6-trace", "policy:wg-v1"
    )


def _worker_spec(
    mode: str = "normal",
    *,
    timeout: float = 2.0,
    response_bytes: int = 1024 * 1024,
) -> ConnectorWorkerSpec:
    return ConnectorWorkerSpec(
        f"whitegoods-{mode}",
        "whitegoods.reference-worker",
        (
            str(Path(sys.executable).resolve()),
            str(LAB_ROOT / "phase6_worker.py"),
            "--mode",
            mode,
        ),
        REPOSITORY_ROOT,
        ("credential://whitegoods/reference",),
        limits=WorkerLimits(timeout, 256 * 1024, response_bytes, 2),
    )


async def _worker_evidence() -> tuple[bool, bool, int, int, str]:
    client = ConnectorWorkerClient(_worker_spec())
    marker_name = "AWS_SECRET_ACCESS_KEY"
    previous = os.environ.get(marker_name)
    os.environ[marker_name] = "phase6-inheritance-test-marker"
    try:
        results = await asyncio.gather(
            client.invoke("postgres.query", {}, request_id="postgres"),
            client.invoke(
                "s3.get",
                {"name": "washing-machine-e21-manual.md"},
                request_id="s3",
            ),
            client.invoke("events.poll", {}, request_id="events"),
            client.invoke("rest.get", {}, request_id="rest"),
            client.invoke("runtime.environment", {}, request_id="environment"),
        )
    finally:
        if previous is None:
            os.environ.pop(marker_name, None)
        else:
            os.environ[marker_name] = previous
    source_shapes = (
        results[0]["rows"] == 6
        and results[1]["bytes"] > 0
        and results[2]["events"] > 0
        and results[3]["records"] > 0
    )
    sensitive_count = len(results[4]["sensitiveVariablesPresent"])
    faults = []
    try:
        await ConnectorWorkerClient(_worker_spec("slow", timeout=0.05)).invoke("rest.get", {})
    except WorkerTimeout:
        faults.append("timeout")
    try:
        await ConnectorWorkerClient(_worker_spec("crash")).invoke("rest.get", {})
    except WorkerCrashed:
        faults.append("crash")
    try:
        await ConnectorWorkerClient(_worker_spec("oversize", response_bytes=512)).invoke(
            "rest.get", {}
        )
    except WorkerProtocolViolation:
        faults.append("oversize")
    cancellation = asyncio.create_task(
        ConnectorWorkerClient(_worker_spec("slow")).invoke("rest.get", {})
    )
    await asyncio.sleep(0.02)
    cancellation.cancel()
    try:
        await cancellation
    except asyncio.CancelledError:
        faults.append("cancellation")
    bounded = ConnectorWorkerClient(_worker_spec("slow"))
    await asyncio.gather(*(bounded.invoke("rest.get", {}) for _ in range(4)))
    profile_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/connector-worker-profile.schema.json").read_text()
    )
    profile_valid = jsonschema.Draft202012Validator(profile_schema).is_valid(
        _worker_spec().to_contract()
    )
    return (
        source_shapes and profile_valid,
        set(faults) == {"timeout", "crash", "oversize", "cancellation"},
        bounded.max_observed_parallelism,
        sensitive_count,
        f"sources=4; faults={sorted(faults)}; profile_valid={profile_valid}",
    )


def _catalog() -> NorthboundToolCatalog:
    action = service_action()
    return NorthboundToolCatalog(
        (
            NorthboundTool(
                "whitegoods.reschedule",
                "Reschedule one approved service appointment",
                action.source_id,
                action.asset_id,
                action.operation,
                action.risk,
                action.approval_mode,
                action.purpose,
                frozenset({"agent.whitegoods-service"}),
            ),
        )
    )


def _mcp_meta(digest: str | None = None) -> dict[str, object]:
    meta: dict[str, object] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "phase6-certifier", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    if digest:
        meta["data.harness/catalogDigest"] = digest
    return meta


def _mcp_call(digest: str) -> dict[str, Any]:
    action = service_action()
    return {
        "jsonrpc": "2.0",
        "id": "mcp-call",
        "method": "tools/call",
        "_meta": _mcp_meta(digest),
        "params": {
            "name": "whitegoods.reschedule",
            "arguments": {
                "actionId": action.action_id,
                "parameters": dict(action.parameters),
                "preconditions": dict(action.preconditions),
                "idempotencyKey": action.idempotency_key,
                "compensation": {
                    "operation": action.compensation.operation,
                    "parameters": dict(action.compensation.parameters),
                    "preconditions": dict(action.compensation.preconditions),
                },
            },
        },
    }


def _protocol_evidence() -> tuple[bool, bool, int, str]:
    catalog = _catalog()
    mcp = Mcp20260728ActionServer(NorthboundActionAdapter(catalog))
    list_request = {
        "jsonrpc": "2.0",
        "id": "mcp-list",
        "method": "tools/list",
        "params": {},
        "_meta": _mcp_meta(),
    }
    first = mcp.handle(list_request, _identity())
    second = mcp.handle(list_request, _identity())
    outsider = mcp.handle(list_request, _identity("agent.outsider"))
    call = _mcp_call(catalog.digest)
    called = mcp.dispatch_http(
        {
            "Content-Type": "application/json",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "whitegoods.reschedule",
        },
        call,
        _identity(),
    )
    mismatch = mcp.dispatch_http(
        {"Content-Type": "application/json", "Mcp-Method": "tools/list"},
        call,
        _identity(),
    )
    stale = mcp.handle(_mcp_call("sha256:" + "0" * 64), _identity())
    mcp_valid = (
        first == second
        and len(first["result"]["tools"]) == 1
        and outsider["result"]["tools"] == []
        and first["result"]["cacheScope"] == "private"
        and called.status == 200
        and called.body["result"]["structuredContent"]["executionRequired"] is True
        and mismatch.status == 400
        and stale["error"]["code"] == -32010
    )
    action = service_action()
    envelope = {
        "protocol": "a2a/1.0",
        "taskId": "task-reschedule-1",
        "requestingAgent": _identity().agent_id,
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
            "compensation": {
                "operation": action.compensation.operation,
                "parameters": dict(action.compensation.parameters),
                "preconditions": dict(action.compensation.preconditions),
            },
        },
    }
    card = A2AAgentCard(
        "Harness actions",
        "Governed source action delegation",
        "https://harness.internal/a2a",
        __version__,
        (A2AAgentSkill("source-action", "Source action", "Bounded action", ("data",)),),
    )
    a2a = A2A10ActionServer(
        A2AActionDelegationAdapter(frozenset({(action.source_id, action.operation)})), card
    )
    request = {
        "jsonrpc": "2.0",
        "id": "a2a-call",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message-1",
                "role": "ROLE_USER",
                "parts": [{"data": envelope, "mediaType": "application/json"}],
            }
        },
    }
    accepted = a2a.handle({"A2A-Version": A2A_PROTOCOL_VERSION}, request, _identity())
    wrong_version = a2a.handle({"A2A-Version": "0.3"}, request, _identity())
    mapped = accepted["result"]["message"]["parts"][0]["data"]
    a2a_valid = (
        card.to_contract()["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        and mapped["actionDigest"] == action.digest
        and mapped["executionRequired"] is True
        and wrong_version["error"]["code"] == -32009
    )
    connector_source = (REPOSITORY_ROOT / "src/data_source_harness/connector.py").read_text()
    coupling = sum(token in connector_source.lower() for token in ("mcp", "a2a", "jsonrpc"))
    return mcp_valid, a2a_valid, coupling, "MCP profile=2026-07-28; A2A profile=1.0"


def _acceptance_packet_evidence() -> tuple[bool, bool, bool, str]:
    evidence_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/cross-plane-evidence-set.schema.json").read_text()
    )
    evidence = json.loads(
        (REPOSITORY_ROOT / "compatibility/phase6-cross-plane-evidence.json").read_text()
    )
    evidence_valid = jsonschema.Draft202012Validator(evidence_schema).is_valid(evidence)
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
    runtime_readiness = readiness(DEFAULT_OUTPUT)
    readiness_schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/disconnected-runtime-readiness.schema.json").read_text()
    )
    readiness_valid = jsonschema.Draft202012Validator(readiness_schema).is_valid(runtime_readiness)
    with zipfile.ZipFile(DEFAULT_OUTPUT) as archive:
        names = set(archive.namelist())
    required = {
        "runtime/openshift/deployment.template.yaml",
        "runtime/openshift/network-policy.yaml",
        "runtime/protocol-profiles.json",
        "compatibility/phase6-cross-plane-evidence.json",
    }
    bundle_valid = readiness_valid and runtime_readiness["artifactIntegrity"] and required <= names
    false_deployment = any(
        runtime_readiness[field]
        for field in (
            "imageDigestsResolved",
            "mirrorVerified",
            "deployed",
            "zeroEgressRuntimeVerified",
            "stakeholderAccepted",
        )
    )
    manifests = [
        yaml.safe_load(path.read_text())
        for path in sorted((LAB_ROOT / "runtime/openshift").glob("*.yaml"))
    ]
    templates_valid = (
        len(manifests) >= 3
        and all(document.get("apiVersion") and document.get("kind") for document in manifests)
        and "IMAGE_DIGEST_REQUIRED"
        in (LAB_ROOT / "runtime/openshift/deployment.template.yaml").read_text()
    )
    return (
        evidence_valid and no_false_acceptance,
        bundle_valid and templates_valid,
        false_deployment,
        f"components={len(evidence['components'])}; blockers={len(runtime_readiness['blockers'])}",
    )


def _protocol_conformance_contracts(mcp_valid: bool, a2a_valid: bool) -> tuple[bool, str]:
    schema = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/protocol-profile-conformance.schema.json").read_text()
    )
    documents = (
        {
            "schemaVersion": "data.harness/v1",
            "profileId": "mcp-2026-07-28-tools",
            "specification": "https://modelcontextprotocol.io/specification/2026-07-28",
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "checks": [{"checkId": "local-profile", "passed": mcp_valid}],
            "upstreamSuite": {"status": "not-run", "reference": None},
        },
        {
            "schemaVersion": "data.harness/v1",
            "profileId": "a2a-1.0-send-message",
            "specification": "https://a2a-protocol.org/latest/specification",
            "protocolVersion": A2A_PROTOCOL_VERSION,
            "checks": [{"checkId": "local-profile", "passed": a2a_valid}],
            "upstreamSuite": {"status": "not-run", "reference": None},
        },
    )
    valid = all(jsonschema.Draft202012Validator(schema).is_valid(item) for item in documents)
    truthful = all(item["upstreamSuite"]["status"] == "not-run" for item in documents)
    return valid and truthful, "two local profiles; upstream suites explicitly not run"


async def certify_phase6() -> Phase6Report:
    phase5 = await certify_phase5()
    (
        source_shapes,
        worker_faults,
        parallelism,
        sensitive_count,
        worker_detail,
    ) = await _worker_evidence()
    mcp_valid, a2a_valid, coupling, protocol_detail = _protocol_evidence()
    protocol_contracts, conformance_detail = _protocol_conformance_contracts(mcp_valid, a2a_valid)
    evidence_valid, bundle_valid, false_deployment, packet_detail = _acceptance_packet_evidence()
    checks = [
        CertificationCheck("regression.phase5", phase5.passed, "Phase-5 certificate rerun"),
        CertificationCheck(
            "workers.production-shape-process-boundary",
            source_shapes,
            worker_detail,
        ),
        CertificationCheck(
            "workers.fault-containment",
            worker_faults and parallelism <= 2 and sensitive_count == 0,
            (
                f"{worker_detail}; max_parallelism={parallelism}; "
                f"inherited_sensitive={sensitive_count}"
            ),
        ),
        CertificationCheck(
            "protocols.versioned-bounded-profiles",
            mcp_valid and a2a_valid and coupling == 0 and protocol_contracts,
            f"{protocol_detail}; {conformance_detail}; connector_coupling={coupling}",
        ),
        CertificationCheck(
            "compatibility.cross-plane-evidence-separated",
            evidence_valid,
            packet_detail,
        ),
        CertificationCheck(
            "airgap.signed-transfer-packet-fails-closed",
            bundle_valid and not false_deployment,
            packet_detail,
        ),
    ]
    plan = json.loads(GQM_PATH.read_text())
    definitions = {item["metricId"]: item for item in plan["metrics"]}
    metrics = (
        _metric(definitions, "P6-M1", float(source_shapes), worker_detail),
        _metric(definitions, "P6-M2", float(worker_faults), worker_detail),
        _metric(definitions, "P6-M3", float(parallelism), "four calls; semaphore bound=2"),
        _metric(definitions, "P6-M4", float(sensitive_count), "sanitized subprocess environment"),
        _metric(definitions, "P6-M5", float(mcp_valid), protocol_detail),
        _metric(definitions, "P6-M6", float(a2a_valid), protocol_detail),
        _metric(definitions, "P6-M7", float(coupling), "connector.py scan"),
        _metric(definitions, "P6-M8", float(not evidence_valid), packet_detail),
        _metric(definitions, "P6-M9", float(bundle_valid), packet_detail),
        _metric(definitions, "P6-M10", float(false_deployment), packet_detail),
    )
    checks.append(
        CertificationCheck(
            "gqm.phase6-plan-complete",
            {item["metricId"] for item in plan["metrics"]} == {item.metric_id for item in metrics},
            f"goals={len(plan['goals'])}; metrics={len(metrics)}",
        )
    )
    passed = all(check.passed for check in checks) and all(metric.passed for metric in metrics)
    return Phase6Report(
        "phase-6",
        "white-goods-production-runtime-scaffold",
        passed,
        tuple(checks),
        metrics,
        (
            "Certifies local OS-process connector isolation, production-shape fixture contracts, "
            "version-pinned MCP/A2A profile adapters, a signed transfer packet and truthful "
            "cross-plane evidence separation. It does not run real PostgreSQL/S3/Kafka/REST "
            "services, upstream protocol suites, pinned container images, oc-mirror, a live "
            "OpenShift deployment, process network isolation, dependency fault drills or "
            "stakeholder acceptance."
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase6-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase6())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
