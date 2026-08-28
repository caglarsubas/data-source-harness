"""Phase-7 laptop-local acceptance readiness without cloud or cluster provisioning."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from data_source_harness.acceptance import (
    AcceptanceStage,
    CostBoundary,
    LiveSourceShape,
    LiveSourceTarget,
    LocalLaptopAcceptanceCampaign,
    ReleaseArtifact,
    StageEvidence,
)
from data_source_harness.evidence import EvidenceStatus
from data_source_harness.local_only import audit_local_only_automation
from reference_labs.white_goods.certify import CertificationCheck, MetricResult, _metric

from .certify_phase6_5 import certify_phase6_5

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = REPOSITORY_ROOT / "compatibility/phase7-release-set.lock.json"
CAMPAIGN_PATH = REPOSITORY_ROOT / "compatibility/phase7-acceptance-readiness.json"
SCHEMA_PATH = REPOSITORY_ROOT / "schemas/v1/live-acceptance-campaign.schema.json"
LOCAL_IMAGE_LOCK_PATH = REPOSITORY_ROOT / "compatibility/phase7-local-images.lock.json"
LOCAL_IMAGE_LOCK_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/v1/local-image-lock.schema.json"
LOCAL_SOURCE_EVIDENCE_PATH = REPOSITORY_ROOT / "compatibility/phase7-local-source-evidence.json"
LOCAL_SOURCE_EVIDENCE_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/v1/local-source-evidence.schema.json"
LOCAL_CROSS_PLANE_EVIDENCE_PATH = (
    REPOSITORY_ROOT / "compatibility/phase7-local-cross-plane-evidence.json"
)
LOCAL_CROSS_PLANE_EVIDENCE_SCHEMA_PATH = (
    REPOSITORY_ROOT / "schemas/v1/local-cross-plane-evidence.schema.json"
)
LOCAL_HARNESS_RUNTIME_EVIDENCE_PATH = (
    REPOSITORY_ROOT / "compatibility/phase7-local-harness-runtime-evidence.json"
)
LOCAL_HARNESS_RUNTIME_EVIDENCE_SCHEMA_PATH = (
    REPOSITORY_ROOT / "schemas/v1/local-harness-runtime-evidence.schema.json"
)
GQM_PATH = Path(__file__).resolve().with_name("phase7_gqm_plan.json")
OBSERVED_AT = datetime(2026, 8, 28, tzinfo=UTC)


@dataclass(frozen=True)
class Phase7ReadinessReport:
    phase: str
    lab_id: str
    passed: bool
    campaign_accepted: bool
    checks: tuple[CertificationCheck, ...]
    metrics: tuple[MetricResult, ...]
    blockers: tuple[str, ...]
    evidence_boundary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _source_targets() -> tuple[LiveSourceTarget, ...]:
    evidence = json.loads(LOCAL_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))
    connector_ids = {
        "whitegoods.postgresql": "whitegoods.erp",
        "whitegoods.object-store": "whitegoods.documents",
        "whitegoods.event-stream": "whitegoods.telemetry",
        "whitegoods.service-api": "whitegoods.service-api",
    }
    return tuple(
        LiveSourceTarget(
            item["sourceId"],
            LiveSourceShape(item["shape"]),
            connector_ids[item["sourceId"]],
            f"credential-ref://phase7/{item['sourceId'].removeprefix('whitegoods.')}",
            item["imageDigest"],
            evidence["passed"],
            datetime.fromisoformat(item["observedAt"]),
            tuple(item["references"]),
        )
        for item in evidence["sources"]
    )


def _observed_evidence(artifacts: tuple[ReleaseArtifact, ...]) -> tuple[StageEvidence, ...]:
    by_component = {item.component: item for item in artifacts}
    source_references = {
        component: (f"{artifact.repository}/commit/{artifact.revision}",)
        for component, artifact in by_component.items()
    }
    exact_main_references = {
        "ADLC": (
            "https://github.com/caglarsubas/agent-hook-v2/actions/runs/33087853316",
            "https://github.com/caglarsubas/agent-hook-v2/actions/runs/33087853263",
        ),
        "model-plane": (
            "https://github.com/caglarsubas/llm_inference_engine/actions/runs/32734407866",
        ),
    }
    observations = [
        StageEvidence(
            component,
            AcceptanceStage.SOURCE,
            EvidenceStatus.PASSED,
            artifact.revision,
            artifact.artifact_digest,
            OBSERVED_AT,
            source_references[component],
        )
        for component, artifact in by_component.items()
    ]
    observations.extend(
        StageEvidence(
            component,
            AcceptanceStage.EXACT_MAIN_CI,
            EvidenceStatus.PASSED,
            by_component[component].revision,
            by_component[component].artifact_digest,
            OBSERVED_AT,
            references,
        )
        for component, references in exact_main_references.items()
    )
    harness_runtime = json.loads(LOCAL_HARNESS_RUNTIME_EVIDENCE_PATH.read_text(encoding="utf-8"))
    harness = by_component["data-source-harness"]
    observations.extend(
        StageEvidence(
            "data-source-harness",
            stage,
            EvidenceStatus.PASSED,
            harness.revision,
            harness.artifact_digest,
            datetime.fromisoformat(harness_runtime["generatedAt"]),
            (f"local-evidence://phase7/data-source-harness/{stage.value}",),
        )
        for stage in (
            AcceptanceStage.LOCAL_IMAGE_LOAD,
            AcceptanceStage.LOCAL_STARTUP,
            AcceptanceStage.RUNTIME,
        )
    )
    return tuple(observations)


def build_readiness_campaign() -> LocalLaptopAcceptanceCampaign:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    artifacts = tuple(
        ReleaseArtifact(
            item["component"],
            item["repository"],
            item["revision"],
            item["artifactDigest"],
        )
        for item in lock["artifacts"]
    )
    return LocalLaptopAcceptanceCampaign(
        lock["campaignId"],
        lock["releaseSet"],
        datetime.fromisoformat(lock["generatedAt"]),
        artifacts,
        _source_targets(),
        _observed_evidence(artifacts),
        CostBoundary(False, (), ()),
    )


def _false_acceptance_count(contract: dict[str, Any]) -> int:
    forged = json.loads(json.dumps(contract))
    forged["accepted"] = True
    forged["blockers"] = []
    try:
        LocalLaptopAcceptanceCampaign.from_contract(forged)
    except ValueError:
        return 0
    return 1


async def certify_phase7_readiness() -> Phase7ReadinessReport:
    phase65 = await certify_phase6_5()
    expected = build_readiness_campaign()
    committed_contract = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    local_image_lock = json.loads(LOCAL_IMAGE_LOCK_PATH.read_text(encoding="utf-8"))
    local_image_lock_schema = json.loads(LOCAL_IMAGE_LOCK_SCHEMA_PATH.read_text(encoding="utf-8"))
    local_source_evidence = json.loads(LOCAL_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8"))
    local_source_evidence_schema = json.loads(
        LOCAL_SOURCE_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    local_cross_plane_evidence = json.loads(
        LOCAL_CROSS_PLANE_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    local_cross_plane_evidence_schema = json.loads(
        LOCAL_CROSS_PLANE_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    local_harness_runtime_evidence = json.loads(
        LOCAL_HARNESS_RUNTIME_EVIDENCE_PATH.read_text(encoding="utf-8")
    )
    local_harness_runtime_evidence_schema = json.loads(
        LOCAL_HARNESS_RUNTIME_EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8")
    )
    schema_errors = list(
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(committed_contract)
    )
    local_image_lock_errors = list(
        jsonschema.Draft202012Validator(local_image_lock_schema).iter_errors(local_image_lock)
    )
    local_source_evidence_errors = list(
        jsonschema.Draft202012Validator(
            local_source_evidence_schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(local_source_evidence)
    )
    local_cross_plane_evidence_errors = list(
        jsonschema.Draft202012Validator(
            local_cross_plane_evidence_schema,
            format_checker=jsonschema.FormatChecker(),
        ).iter_errors(local_cross_plane_evidence)
    )
    local_harness_runtime_evidence_errors = list(
        jsonschema.Draft202012Validator(
            local_harness_runtime_evidence_schema,
            format_checker=jsonschema.FormatChecker(),
        ).iter_errors(local_harness_runtime_evidence)
    )
    try:
        parsed = LocalLaptopAcceptanceCampaign.from_contract(committed_contract)
        parse_error = ""
    except (KeyError, TypeError, ValueError) as exc:
        parsed = expected
        parse_error = str(exc)

    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    exact_main_components = {
        item.component
        for item in parsed.evidence
        if item.stage is AcceptanceStage.EXACT_MAIN_CI and item.status is EvidenceStatus.PASSED
    }
    false_accepts = _false_acceptance_count(committed_contract)
    automation_violations = audit_local_only_automation(REPOSITORY_ROOT)
    compose = yaml.safe_load(
        (REPOSITORY_ROOT / "reference_labs/white_goods/live/compose.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    services = compose.get("services", {})
    expected_source_services = {"postgresql", "object-store", "event-stream", "service-api"}
    expected_services = expected_source_services | {"harness-acceptance"}
    locked_images = {item["sourceId"]: item["imageDigest"] for item in local_image_lock["images"]}
    observed_images = {
        item["sourceId"]: item["imageDigest"] for item in local_source_evidence["sources"]
    }
    expected_local_checks = {
        "postgresql.seeded-query",
        "object-store.seeded-list",
        "event-stream.seeded-consume",
        "service-api.auth-pagination",
        "network.internal",
        "network.no-published-ports",
        "network.public-egress-denied",
    }
    observed_local_checks = {item["checkId"] for item in local_source_evidence["checks"]}
    expected_records = {
        "whitegoods.postgresql": 6,
        "whitegoods.object-store": 4,
        "whitegoods.event-stream": 9,
        "whitegoods.service-api": 3,
    }
    observed_records = {
        item["sourceId"]: item["recordsObserved"] for item in local_source_evidence["sources"]
    }
    locked_platforms = {
        f"{item['os']}/{item['architecture']}" for item in local_image_lock["images"]
    }
    expected_cross_plane_checks = {
        "repositories.revision-bound",
        "sdk.runtime-receipt-built",
        "adlc.runtime-receipt-accepted",
        "adlc.forged-receipt-denied",
        "model-plane.health-route",
        "model-plane.tenant-bound-rerank",
        "harness.governed-ranking",
        "boundary.zero-external-resources",
    }
    observed_cross_plane_checks = {item["checkId"] for item in local_cross_plane_evidence["checks"]}
    cross_plane_components = {
        item["component"] for item in local_cross_plane_evidence["components"]
    }
    cross_plane_surface_digests = {
        item["surfaceDigest"] for item in local_cross_plane_evidence["components"]
    }
    expected_harness_runtime_checks = {
        "runtime.connectors-healthy",
        "mutation.preview-policy-bound",
        "mutation.human-approval-required",
        "mutation.postgresql-executed",
        "mutation.gateway-replay-idempotent",
        "mutation.source-replay-after-gateway-restart",
        "mutation.stale-precondition-denied",
        "mutation.compensated",
        "mutation.audit-chain-payload-free",
        "mutation.telemetry-tenant-bound-payload-free",
        "harness.discovery-four-shapes",
        "harness.bounded-postgresql-query",
        "harness.s3-decode-untrusted",
        "harness.kafka-bounded-snapshot",
        "harness.rest-auth-pagination",
        "harness.exact-provenance",
        "harness.semantic-resolution",
        "governance.read-only-action-denied",
        "runtime.gateway-telemetry",
        "artifact.local-image-loaded",
        "artifact.offline-wheelhouse-bound",
        "runtime.internal-network-only",
    }
    observed_harness_runtime_checks = {
        item["checkId"] for item in local_harness_runtime_evidence["checks"]
    }
    harness_artifact = next(
        item for item in expected.artifacts if item.component == "data-source-harness"
    )
    local_only_compose = (
        set(services) == expected_services
        and compose.get("networks", {}).get("lab-internal", {}).get("internal") is True
        and all(
            services[name].get("profiles") == ["phase7-local"] for name in expected_source_services
        )
        and services["harness-acceptance"].get("profiles") == ["phase7-harness"]
        and all(service.get("pull_policy") == "never" for service in services.values())
        and all("ports" not in service for service in services.values())
        and all(
            isinstance(service.get("image"), str)
            and service["image"].startswith("${PHASE7_")
            and ":?" in service["image"]
            for service in services.values()
        )
    )
    checks = (
        CertificationCheck("regression.phase6.5", phase65.passed, f"passed={phase65.passed}"),
        CertificationCheck(
            "campaign.schema-and-derived-fields",
            not schema_errors and not parse_error,
            parse_error
            or "; ".join(error.message for error in schema_errors)
            or f"blockers={len(parsed.blockers)}",
        ),
        CertificationCheck(
            "campaign.deterministic-snapshot",
            committed_contract == expected.to_contract(),
            f"releaseSetDigest={expected.release_set_digest}",
        ),
        CertificationCheck(
            "campaign.release-lock-bound",
            committed_contract.get("artifacts") == lock.get("artifacts"),
            f"artifacts={len(lock.get('artifacts', []))}",
        ),
        CertificationCheck(
            "campaign.partial-evidence-not-accepted",
            not parsed.accepted and false_accepts == 0 and bool(parsed.blockers),
            f"accepted={parsed.accepted}; falseAccepts={false_accepts}",
        ),
        CertificationCheck(
            "campaign.exact-main-observations",
            exact_main_components == {"ADLC", "model-plane"},
            f"observed={','.join(sorted(exact_main_components))}; "
            "data-source-harness,Python-SDK=missing",
        ),
        CertificationCheck(
            "campaign.local-source-boundary",
            {item.shape for item in parsed.sources} == set(LiveSourceShape)
            and all(
                item.endpoint_reference.startswith("credential-ref://") for item in parsed.sources
            )
            and all(item.live_verified for item in parsed.sources),
            f"targets={len(parsed.sources)}; "
            f"verified={sum(item.live_verified for item in parsed.sources)}",
        ),
        CertificationCheck(
            "campaign.local-source-evidence",
            not local_image_lock_errors
            and not local_source_evidence_errors
            and local_source_evidence["passed"] is True
            and local_source_evidence["externalResourcesCreated"] == []
            and locked_images == observed_images
            and observed_local_checks == expected_local_checks
            and len(local_source_evidence["checks"]) == len(expected_local_checks)
            and observed_records == expected_records
            and locked_platforms == {local_image_lock["platform"]}
            and len(set(locked_images.values())) == 4,
            f"platform={local_image_lock['platform']}; "
            f"checks={len(local_source_evidence['checks'])}; "
            f"externalResources={len(local_source_evidence['externalResourcesCreated'])}",
        ),
        CertificationCheck(
            "campaign.local-only-compose-handoff",
            local_only_compose,
            f"services={','.join(sorted(services))}; profiles=phase7-local,phase7-harness; "
            "pullPolicy=never; publishedPorts=0",
        ),
        CertificationCheck(
            "campaign.local-cross-plane-evidence",
            not local_cross_plane_evidence_errors
            and local_cross_plane_evidence["passed"] is True
            and local_cross_plane_evidence["externalResourcesCreated"] == []
            and observed_cross_plane_checks == expected_cross_plane_checks
            and len(local_cross_plane_evidence["checks"]) == len(expected_cross_plane_checks)
            and cross_plane_components == {"ADLC", "Python-SDK", "model-plane"}
            and len(cross_plane_surface_digests) == 3
            and local_cross_plane_evidence["rerank"]["resultOrder"] == [1, 2, 0]
            and local_cross_plane_evidence["rerank"]["harnessRanking"] == [1, 2, 0]
            and local_cross_plane_evidence["rerank"]["tenant"]
            == {"tenant": "whitegoods-lab", "orgId": "org-lab"},
            f"components={','.join(sorted(cross_plane_components))}; "
            f"checks={len(local_cross_plane_evidence['checks'])}; "
            f"externalResources={len(local_cross_plane_evidence['externalResourcesCreated'])}",
        ),
        CertificationCheck(
            "campaign.local-harness-runtime-evidence",
            not local_harness_runtime_evidence_errors
            and local_harness_runtime_evidence["passed"] is True
            and local_harness_runtime_evidence["externalResourcesCreated"] == []
            and observed_harness_runtime_checks == expected_harness_runtime_checks
            and local_harness_runtime_evidence["revision"] == harness_artifact.revision
            and local_harness_runtime_evidence["artifactDigest"] == harness_artifact.artifact_digest
            and local_harness_runtime_evidence["networkMode"] == "compose-internal",
            f"checks={len(observed_harness_runtime_checks)}; "
            f"externalResources={len(local_harness_runtime_evidence['externalResourcesCreated'])}",
        ),
        CertificationCheck(
            "campaign.no-cloud-or-cluster-mutation",
            not parsed.cost_boundary.provisioning_authorized
            and not parsed.cost_boundary.resources_created
            and not parsed.cost_boundary.external_mutations,
            "provisioningAuthorized=false; resourcesCreated=0; externalMutations=0",
        ),
        CertificationCheck(
            "campaign.local-only-automation",
            not automation_violations,
            "violations=" + (",".join(automation_violations) or "none"),
        ),
    )

    gqm = json.loads(GQM_PATH.read_text(encoding="utf-8"))
    definitions = {item["metricId"]: item for item in gqm["metrics"]}
    metrics = (
        _metric(
            definitions, "P7R-M1", float(not schema_errors and not parse_error), "schema+parser"
        ),
        _metric(definitions, "P7R-M2", float(false_accepts), "forged derived fields"),
        _metric(definitions, "P7R-M3", float(len(parsed.artifacts)), "exact revisions"),
        _metric(definitions, "P7R-M4", float(len(exact_main_components)), "SDK CI absent"),
        _metric(definitions, "P7R-M5", float(len(parsed.sources)), "credential references"),
        _metric(
            definitions,
            "P7R-M6",
            float(len(parsed.cost_boundary.resources_created)),
            "readiness-only",
        ),
        _metric(
            definitions,
            "P7R-M7",
            float(len(parsed.cost_boundary.external_mutations)),
            "readiness-only",
        ),
        _metric(
            definitions,
            "P7R-M8",
            float(sum(item.live_verified for item in parsed.sources)),
            "local source observations",
        ),
        _metric(
            definitions,
            "P7R-M9",
            float(len(local_source_evidence["externalResourcesCreated"])),
            "local source lab",
        ),
        _metric(
            definitions,
            "P7R-M10",
            float(len(cross_plane_components)),
            "revision-bound SDK, ADLC and model-plane contract surfaces",
        ),
        _metric(
            definitions,
            "P7R-M11",
            float(len(local_cross_plane_evidence["externalResourcesCreated"])),
            "local cross-plane contract lab",
        ),
        _metric(
            definitions,
            "P7R-M12",
            float(len(local_harness_runtime_evidence["sourceRecordCounts"])),
            "real harness connector paths",
        ),
        _metric(
            definitions,
            "P7R-M13",
            float(len(local_harness_runtime_evidence["externalResourcesCreated"])),
            "local harness runtime lab",
        ),
        _metric(
            definitions,
            "P7R-M14",
            float(
                sum(
                    item["checkId"].startswith("mutation.")
                    for item in local_harness_runtime_evidence["checks"]
                )
            ),
            "governed PostgreSQL mutation lifecycle",
        ),
    )
    return Phase7ReadinessReport(
        "phase-7-readiness",
        "white-goods-local-laptop-acceptance",
        all(check.passed for check in checks) and all(metric.passed for metric in metrics),
        parsed.accepted,
        checks,
        metrics,
        parsed.blockers,
        "This readiness certificate validates the fail-closed laptop-local Phase 7 campaign "
        "ledger, verifies four digest-bound source services, runs the revision-bound SDK receipt, "
        "ADLC and model-plane contract seams, and executes the digest-bound harness image through "
        "four real connector paths plus one governed PostgreSQL mutation lifecycle locally. "
        "GCP, OpenShift and remote-cluster provisioning are "
        "prohibited. "
        "It does not claim harness publication or exact-main CI for this candidate, other "
        "platform images/startup, protocol conformance, fault, soak or stakeholder acceptance.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-readiness-certify")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--campaign-output", type=Path)
    args = parser.parse_args(argv)
    if args.campaign_output:
        contract = build_readiness_campaign().to_contract()
        args.campaign_output.write_text(
            json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    report = asyncio.run(certify_phase7_readiness())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
