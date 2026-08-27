"""Cross-plane evidence states that cannot collapse CI into runtime acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvidenceStatus(StrEnum):
    MISSING = "missing"
    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True)
class EvidenceClaim:
    status: EvidenceStatus
    observed_at: datetime | None
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("evidence observation time must be timezone-aware")
        if self.status in {EvidenceStatus.PASSED, EvidenceStatus.FAILED}:
            if self.observed_at is None or not self.references:
                raise ValueError("observed evidence requires time and references")
        elif self.observed_at is not None or self.references:
            raise ValueError("missing/not-applicable evidence cannot carry observations")
        if len(self.references) != len(set(self.references)) or any(
            not reference for reference in self.references
        ):
            raise ValueError("evidence references must be non-empty and unique")

    def to_contract(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "observedAt": self.observed_at.isoformat() if self.observed_at else None,
            "references": list(self.references),
        }


@dataclass(frozen=True)
class PlaneEvidence:
    component: str
    repository: str
    revision: str
    contract: EvidenceClaim
    ci: EvidenceClaim
    published: EvidenceClaim
    deployed: EvidenceClaim
    runtime_verified: EvidenceClaim
    fault_verified: EvidenceClaim
    stakeholder_accepted: EvidenceClaim

    def __post_init__(self) -> None:
        if not self.component or not self.repository:
            raise ValueError("plane identity and repository are required")
        if not re.fullmatch(r"[0-9a-f]{40}", self.revision):
            raise ValueError("plane revision must be an exact Git SHA")

    def to_contract(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "repository": self.repository,
            "revision": self.revision,
            "evidence": {
                "contract": self.contract.to_contract(),
                "ci": self.ci.to_contract(),
                "published": self.published.to_contract(),
                "deployed": self.deployed.to_contract(),
                "runtimeVerified": self.runtime_verified.to_contract(),
                "faultVerified": self.fault_verified.to_contract(),
                "stakeholderAccepted": self.stakeholder_accepted.to_contract(),
            },
        }


@dataclass(frozen=True)
class CrossPlaneEvidenceSet:
    release_set: str
    generated_at: datetime
    components: tuple[PlaneEvidence, ...]

    def __post_init__(self) -> None:
        if not self.release_set or self.generated_at.tzinfo is None or not self.components:
            raise ValueError("release-set identity, time and components are required")
        names = [component.component for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("cross-plane component names must be unique")

    @property
    def combined_runtime_accepted(self) -> bool:
        required = (
            claim
            for component in self.components
            for claim in (
                component.contract,
                component.ci,
                component.published,
                component.deployed,
                component.runtime_verified,
                component.fault_verified,
                component.stakeholder_accepted,
            )
        )
        return all(claim.status is EvidenceStatus.PASSED for claim in required)

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "releaseSet": self.release_set,
            "generatedAt": self.generated_at.isoformat(),
            "combinedRuntimeAccepted": self.combined_runtime_accepted,
            "components": [component.to_contract() for component in self.components],
        }
