from data_source_harness.promotion import (
    CompatibilityEntry,
    CompatibilityMatrix,
    EvidenceKind,
    EvidenceStatus,
    PromotionEvidence,
    PromotionReadinessEvaluator,
)

REVISION = "a" * 40


def item(kind: EvidenceKind, status: EvidenceStatus = EvidenceStatus.PASSED) -> PromotionEvidence:
    return PromotionEvidence(f"{kind.value}-1", kind, status, REVISION, f"sha256:{kind.value}")


def matrix(compatible: bool = True) -> CompatibilityMatrix:
    return CompatibilityMatrix(
        "phase-2",
        (CompatibilityEntry("ADLC", "b" * 40, compatible, "compat-1"),),
    )


def test_readiness_requires_distinct_evidence_states_and_compatibility() -> None:
    evaluator = PromotionReadinessEvaluator()
    partial = evaluator.evaluate(
        (item(EvidenceKind.SOURCE), item(EvidenceKind.CI), item(EvidenceKind.RUNTIME)), matrix()
    )
    assert not partial.ready_for_adlc_decision
    assert partial.missing_kinds == (EvidenceKind.STAKEHOLDER,)
    complete = evaluator.evaluate(tuple(item(kind) for kind in EvidenceKind), matrix())
    assert complete.ready_for_adlc_decision


def test_failed_runtime_or_incompatible_release_set_blocks_readiness() -> None:
    evidence = tuple(
        item(kind, EvidenceStatus.FAILED if kind is EvidenceKind.RUNTIME else EvidenceStatus.PASSED)
        for kind in EvidenceKind
    )
    readiness = PromotionReadinessEvaluator().evaluate(evidence, matrix(False))
    assert readiness.failed_kinds == (EvidenceKind.RUNTIME,)
    assert not readiness.compatibility_ready


def test_explicit_missing_status_is_reported_as_missing() -> None:
    evidence = tuple(
        item(
            kind,
            EvidenceStatus.MISSING if kind is EvidenceKind.STAKEHOLDER else EvidenceStatus.PASSED,
        )
        for kind in EvidenceKind
    )
    readiness = PromotionReadinessEvaluator().evaluate(evidence, matrix())
    assert readiness.missing_kinds == (EvidenceKind.STAKEHOLDER,)
