"""Reference-lab promotion readiness without usurping ADLC decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class EvidenceKind(StrEnum):
    SOURCE = "source"
    CI = "ci"
    RUNTIME = "runtime"
    STAKEHOLDER = "stakeholder"


class EvidenceStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    MISSING = "missing"


@dataclass(frozen=True)
class PromotionEvidence:
    evidence_id: str
    kind: EvidenceKind
    status: EvidenceStatus
    revision: str
    digest: str

    def __post_init__(self) -> None:
        if (
            not self.evidence_id
            or not self.digest
            or not re.fullmatch(r"[0-9a-f]{40}", self.revision)
        ):
            raise ValueError("promotion evidence requires identity, digest and exact revision")


@dataclass(frozen=True)
class CompatibilityEntry:
    component: str
    revision: str
    compatible: bool
    evidence_id: str

    def __post_init__(self) -> None:
        if (
            not self.component
            or not self.evidence_id
            or not re.fullmatch(r"[0-9a-f]{40}", self.revision)
        ):
            raise ValueError("compatibility entries require component, exact revision and evidence")


@dataclass(frozen=True)
class CompatibilityMatrix:
    release_set: str
    entries: tuple[CompatibilityEntry, ...]

    @property
    def compatible(self) -> bool:
        names = [item.component for item in self.entries]
        return (
            bool(self.entries)
            and len(names) == len(set(names))
            and all(item.compatible for item in self.entries)
        )


@dataclass(frozen=True)
class PromotionReadiness:
    ready_for_adlc_decision: bool
    failed_kinds: tuple[EvidenceKind, ...]
    missing_kinds: tuple[EvidenceKind, ...]
    compatibility_ready: bool


class PromotionReadinessEvaluator:
    REQUIRED = frozenset(EvidenceKind)

    def evaluate(
        self, evidence: tuple[PromotionEvidence, ...], matrix: CompatibilityMatrix
    ) -> PromotionReadiness:
        by_kind = {item.kind: item for item in evidence}
        missing = tuple(
            sorted(
                (self.REQUIRED - set(by_kind))
                | {kind for kind, item in by_kind.items() if item.status is EvidenceStatus.MISSING},
                key=lambda item: item.value,
            )
        )
        failed = tuple(
            sorted(
                (kind for kind, item in by_kind.items() if item.status is EvidenceStatus.FAILED),
                key=lambda item: item.value,
            )
        )
        nonpassing = any(item.status is not EvidenceStatus.PASSED for item in by_kind.values())
        ready = not missing and not failed and not nonpassing and matrix.compatible
        return PromotionReadiness(ready, failed, missing, matrix.compatible)
