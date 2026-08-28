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
    return (
        LiveSourceTarget(
            "whitegoods.postgresql",
            LiveSourceShape.POSTGRESQL,
            "whitegoods.erp",
            "credential-ref://phase7/postgresql",
        ),
        LiveSourceTarget(
            "whitegoods.object-store",
            LiveSourceShape.S3_COMPATIBLE,
            "whitegoods.documents",
            "credential-ref://phase7/object-store",
        ),
        LiveSourceTarget(
            "whitegoods.event-stream",
            LiveSourceShape.KAFKA_COMPATIBLE,
            "whitegoods.telemetry",
            "credential-ref://phase7/event-stream",
        ),
        LiveSourceTarget(
            "whitegoods.service-api",
            LiveSourceShape.REST,
            "whitegoods.service-api",
            "credential-ref://phase7/service-api",
        ),
    )


def _observed_evidence(artifacts: tuple[ReleaseArtifact, ...]) -> tuple[StageEvidence, ...]:
    by_component = {item.component: item for item in artifacts}
    source_references = {
        component: (f"{artifact.repository}/commit/{artifact.revision}",)
        for component, artifact in by_component.items()
    }
    exact_main_references = {
        "data-source-harness": (
            "https://github.com/caglarsubas/data-source-harness/actions/runs/33092591951",
            "https://github.com/caglarsubas/data-source-harness/actions/runs/33092592077",
        ),
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
    schema_errors = list(
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).iter_errors(committed_contract)
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
    expected_services = {"postgresql", "object-store", "event-stream", "service-api"}
    local_only_compose = (
        set(services) == expected_services
        and compose.get("networks", {}).get("lab-internal", {}).get("internal") is True
        and all(service.get("profiles") == ["phase7-local"] for service in services.values())
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
            exact_main_components == {"data-source-harness", "ADLC", "model-plane"},
            f"observed={','.join(sorted(exact_main_components))}; Python-SDK=missing",
        ),
        CertificationCheck(
            "campaign.local-source-boundary",
            {item.shape for item in parsed.sources} == set(LiveSourceShape)
            and all(
                item.endpoint_reference.startswith("credential-ref://") for item in parsed.sources
            )
            and not any(item.live_verified for item in parsed.sources),
            f"targets={len(parsed.sources)}; verified=0",
        ),
        CertificationCheck(
            "campaign.local-only-compose-handoff",
            local_only_compose,
            f"services={','.join(sorted(services))}; profile=phase7-local; "
            "pullPolicy=never; publishedPorts=0",
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
        "ledger and records read-only source/CI observations. GCP, OpenShift and remote-cluster "
        "provisioning are prohibited. It does not claim artifact publication, local image load, "
        "local startup, runtime, protocol conformance, fault, soak or stakeholder acceptance.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase7-readiness-certify")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(certify_phase7_readiness())
    rendered = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
