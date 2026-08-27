from __future__ import annotations

from datetime import UTC, datetime

import pytest

from data_source_harness.evidence import (
    CrossPlaneEvidenceSet,
    EvidenceClaim,
    EvidenceStatus,
    PlaneEvidence,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)


def missing() -> EvidenceClaim:
    return EvidenceClaim(EvidenceStatus.MISSING, None)


def test_cross_plane_evidence_cannot_promote_contract_proof_to_runtime_acceptance() -> None:
    contract = EvidenceClaim(EvidenceStatus.PASSED, NOW, ("contract://phase6",))
    component = PlaneEvidence(
        "ADLC",
        "https://github.com/caglarsubas/agent-hook-v2.git",
        "a" * 40,
        contract,
        missing(),
        missing(),
        missing(),
        missing(),
        missing(),
        missing(),
    )
    evidence = CrossPlaneEvidenceSet("phase-6", NOW, (component,))
    assert not evidence.combined_runtime_accepted
    assert evidence.to_contract()["components"][0]["evidence"]["deployed"]["status"] == "missing"


def test_passed_evidence_requires_observation_and_reference() -> None:
    with pytest.raises(ValueError, match="requires time and references"):
        EvidenceClaim(EvidenceStatus.PASSED, None)


def test_evidence_references_must_be_non_empty_and_unique() -> None:
    with pytest.raises(ValueError, match="non-empty and unique"):
        EvidenceClaim(EvidenceStatus.PASSED, NOW, ("contract://phase6", "contract://phase6"))
