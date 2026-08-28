"""Fail-closed evidence ledger for a live, cross-plane acceptance campaign."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from .evidence import EvidenceStatus

REQUIRED_ACCEPTANCE_COMPONENTS = frozenset(
    {
        "data-source-harness",
        "ADLC",
        "Python-SDK",
        "OCP-reference-lab",
        "model-plane",
    }
)


class AcceptanceStage(StrEnum):
    SOURCE = "source"
    PR_CI = "pr-ci"
    EXACT_MAIN_CI = "exact-main-ci"
    PUBLICATION = "publication"
    MIRROR = "mirror"
    DEPLOYMENT = "deployment"
    RUNTIME = "runtime"
    FAULT = "fault"
    SOAK = "soak"
    PROTOCOL_CONFORMANCE = "protocol-conformance"
    STAKEHOLDER = "stakeholder"


ARTIFACT_REQUIRED_STAGES = frozenset(
    {
        AcceptanceStage.PUBLICATION,
        AcceptanceStage.MIRROR,
        AcceptanceStage.DEPLOYMENT,
        AcceptanceStage.RUNTIME,
        AcceptanceStage.FAULT,
        AcceptanceStage.SOAK,
        AcceptanceStage.PROTOCOL_CONFORMANCE,
        AcceptanceStage.STAKEHOLDER,
    }
)


class LiveSourceShape(StrEnum):
    POSTGRESQL = "postgresql"
    S3_COMPATIBLE = "s3-compatible"
    KAFKA_COMPATIBLE = "kafka-compatible"
    REST = "rest"


def _require_sha(value: str, label: str) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label} must be an exact Git SHA")


def _require_digest(value: str | None, label: str) -> None:
    if value is not None and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} must be a sha256 digest")


def _require_references(references: tuple[str, ...]) -> None:
    if (
        not references
        or len(references) != len(set(references))
        or any(not reference for reference in references)
    ):
        raise ValueError("observed evidence references must be non-empty and unique")


@dataclass(frozen=True)
class ReleaseArtifact:
    component: str
    repository: str
    revision: str
    artifact_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.component:
            raise ValueError("release component is required")
        parsed = urlparse(self.repository)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("release repository must be an HTTPS URL")
        _require_sha(self.revision, "release revision")
        _require_digest(self.artifact_digest, "release artifact")

    def to_contract(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "repository": self.repository,
            "revision": self.revision,
            "artifactDigest": self.artifact_digest,
        }


@dataclass(frozen=True)
class LiveSourceTarget:
    source_id: str
    shape: LiveSourceShape
    connector_id: str
    endpoint_reference: str
    image_digest: str | None = None
    live_verified: bool = False
    observed_at: datetime | None = None
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_id or not self.connector_id:
            raise ValueError("live source and connector identities are required")
        prefix = "credential-ref://"
        reference_name = self.endpoint_reference.removeprefix(prefix)
        if (
            not self.endpoint_reference.startswith(prefix)
            or not reference_name
            or reference_name.startswith("/")
        ):
            raise ValueError("live endpoints must use credential references")
        _require_digest(self.image_digest, "source image")
        if self.live_verified:
            if self.image_digest is None or self.observed_at is None:
                raise ValueError("verified live sources require image digest and observation time")
            if self.observed_at.tzinfo is None:
                raise ValueError("live source observation time must be timezone-aware")
            _require_references(self.references)
        elif self.observed_at is not None or self.references:
            raise ValueError("unverified live sources cannot carry observations")

    def to_contract(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "shape": self.shape.value,
            "connectorId": self.connector_id,
            "endpointReference": self.endpoint_reference,
            "imageDigest": self.image_digest,
            "liveVerified": self.live_verified,
            "observedAt": self.observed_at.isoformat() if self.observed_at else None,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class StageEvidence:
    component: str
    stage: AcceptanceStage
    status: EvidenceStatus
    revision: str
    artifact_digest: str | None
    observed_at: datetime
    references: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.status not in {EvidenceStatus.PASSED, EvidenceStatus.FAILED}:
            raise ValueError("stage evidence must be an observed pass or failure")
        _require_sha(self.revision, "evidence revision")
        _require_digest(self.artifact_digest, "evidence artifact")
        if self.observed_at.tzinfo is None:
            raise ValueError("stage evidence time must be timezone-aware")
        _require_references(self.references)
        if self.stage in ARTIFACT_REQUIRED_STAGES and self.artifact_digest is None:
            raise ValueError(f"{self.stage.value} evidence must bind an artifact digest")

    def to_contract(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "stage": self.stage.value,
            "status": self.status.value,
            "revision": self.revision,
            "artifactDigest": self.artifact_digest,
            "observedAt": self.observed_at.isoformat(),
            "references": list(self.references),
        }


@dataclass(frozen=True)
class CostBoundary:
    provisioning_authorized: bool = False
    resources_created: tuple[str, ...] = ()
    external_mutations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provisioning_authorized and (self.resources_created or self.external_mutations):
            raise ValueError("unauthorized campaign cannot record external mutations")
        for values in (self.resources_created, self.external_mutations):
            if len(values) != len(set(values)) or any(not value for value in values):
                raise ValueError("cost-boundary entries must be non-empty and unique")

    def to_contract(self) -> dict[str, Any]:
        return {
            "provisioningAuthorized": self.provisioning_authorized,
            "resourcesCreated": list(self.resources_created),
            "externalMutations": list(self.external_mutations),
        }


@dataclass(frozen=True)
class LiveAcceptanceCampaign:
    campaign_id: str
    release_set: str
    generated_at: datetime
    artifacts: tuple[ReleaseArtifact, ...]
    sources: tuple[LiveSourceTarget, ...]
    evidence: tuple[StageEvidence, ...]
    cost_boundary: CostBoundary = CostBoundary()

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.release_set:
            raise ValueError("campaign and release-set identities are required")
        if self.generated_at.tzinfo is None:
            raise ValueError("campaign generation time must be timezone-aware")
        components = [artifact.component for artifact in self.artifacts]
        if (
            len(components) != len(set(components))
            or set(components) != REQUIRED_ACCEPTANCE_COMPONENTS
        ):
            raise ValueError("campaign must contain exactly the five platform components")
        shapes = [source.shape for source in self.sources]
        source_ids = [source.source_id for source in self.sources]
        connector_ids = [source.connector_id for source in self.sources]
        if (
            len(shapes) != len(set(shapes))
            or set(shapes) != set(LiveSourceShape)
            or len(source_ids) != len(set(source_ids))
            or len(connector_ids) != len(set(connector_ids))
        ):
            raise ValueError("campaign requires four unique representative live source shapes")
        evidence_keys = [(item.component, item.stage) for item in self.evidence]
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("component/stage evidence must be unique")
        artifact_by_component = {item.component: item for item in self.artifacts}
        for item in self.evidence:
            artifact = artifact_by_component.get(item.component)
            if artifact is None:
                raise ValueError("evidence component is outside the release set")
            if item.revision != artifact.revision:
                raise ValueError("evidence revision does not match the release set")
            if item.artifact_digest != artifact.artifact_digest:
                raise ValueError("evidence artifact digest does not match the release set")

    @property
    def release_set_digest(self) -> str:
        payload = [
            artifact.to_contract() for artifact in sorted(self.artifacts, key=lambda x: x.component)
        ]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for artifact in sorted(self.artifacts, key=lambda item: item.component):
            if artifact.artifact_digest is None:
                blockers.append(f"{artifact.component}:artifact-digest-missing")
        for source in sorted(self.sources, key=lambda item: item.shape.value):
            if source.image_digest is None:
                blockers.append(f"{source.source_id}:image-digest-missing")
            if not source.live_verified:
                blockers.append(f"{source.source_id}:live-verification-missing")
        evidence_by_key = {(item.component, item.stage): item for item in self.evidence}
        for component in sorted(REQUIRED_ACCEPTANCE_COMPONENTS):
            for stage in AcceptanceStage:
                item = evidence_by_key.get((component, stage))
                if item is None:
                    blockers.append(f"{component}:{stage.value}:missing")
                elif item.status is EvidenceStatus.FAILED:
                    blockers.append(f"{component}:{stage.value}:failed")
        return tuple(blockers)

    @property
    def accepted(self) -> bool:
        return not self.blockers

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "campaignId": self.campaign_id,
            "releaseSet": self.release_set,
            "releaseSetDigest": self.release_set_digest,
            "generatedAt": self.generated_at.isoformat(),
            "artifacts": [item.to_contract() for item in self.artifacts],
            "sources": [item.to_contract() for item in self.sources],
            "evidence": [item.to_contract() for item in self.evidence],
            "costBoundary": self.cost_boundary.to_contract(),
            "accepted": self.accepted,
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_contract(cls, value: dict[str, Any]) -> LiveAcceptanceCampaign:
        """Parse a contract and reject any forged derived acceptance fields."""

        artifacts = tuple(
            ReleaseArtifact(
                item["component"],
                item["repository"],
                item["revision"],
                item["artifactDigest"],
            )
            for item in value["artifacts"]
        )
        sources = tuple(
            LiveSourceTarget(
                item["sourceId"],
                LiveSourceShape(item["shape"]),
                item["connectorId"],
                item["endpointReference"],
                item["imageDigest"],
                item["liveVerified"],
                datetime.fromisoformat(item["observedAt"])
                if item["observedAt"] is not None
                else None,
                tuple(item["references"]),
            )
            for item in value["sources"]
        )
        evidence = tuple(
            StageEvidence(
                item["component"],
                AcceptanceStage(item["stage"]),
                EvidenceStatus(item["status"]),
                item["revision"],
                item["artifactDigest"],
                datetime.fromisoformat(item["observedAt"]),
                tuple(item["references"]),
            )
            for item in value["evidence"]
        )
        boundary = value["costBoundary"]
        campaign = cls(
            value["campaignId"],
            value["releaseSet"],
            datetime.fromisoformat(value["generatedAt"]),
            artifacts,
            sources,
            evidence,
            CostBoundary(
                boundary["provisioningAuthorized"],
                tuple(boundary["resourcesCreated"]),
                tuple(boundary["externalMutations"]),
            ),
        )
        if value.get("schemaVersion") != "data.harness/v1":
            raise ValueError("unsupported live acceptance schema version")
        if value.get("releaseSetDigest") != campaign.release_set_digest:
            raise ValueError("declared release-set digest does not match campaign artifacts")
        if value.get("accepted") is not campaign.accepted:
            raise ValueError("declared acceptance does not match observed evidence")
        if value.get("blockers") != list(campaign.blockers):
            raise ValueError("declared blockers do not match observed evidence")
        return campaign
