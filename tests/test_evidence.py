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
    components = tuple(
        PlaneEvidence(
            name,
            f"https://example.test/{name}",
            revision * 40,
            contract,
            missing(),
            missing(),
            missing(),
            missing(),
            missing(),
            missing(),
        )
        for name, revision in (
            ("ADLC", "a"),
            ("Python-SDK", "b"),
            ("OCP-reference-lab", "c"),
            ("model-plane", "d"),
        )
    )
    evidence = CrossPlaneEvidenceSet("phase-6", NOW, components)
    assert not evidence.combined_runtime_accepted
    assert evidence.to_contract()["components"][0]["evidence"]["deployed"]["status"] == "missing"


def test_cross_plane_evidence_requires_the_complete_platform_set() -> None:
    component = PlaneEvidence(
        "ADLC",
        "https://example.test/adlc",
        "a" * 40,
        EvidenceClaim(EvidenceStatus.PASSED, NOW, ("contract://phase6",)),
        missing(),
        missing(),
        missing(),
        missing(),
        missing(),
        missing(),
    )
    with pytest.raises(ValueError, match="exactly ADLC"):
        CrossPlaneEvidenceSet("phase-6", NOW, (component,))


def test_passed_evidence_requires_observation_and_reference() -> None:
    with pytest.raises(ValueError, match="requires time and references"):
        EvidenceClaim(EvidenceStatus.PASSED, None)


def test_evidence_references_must_be_non_empty_and_unique() -> None:
    with pytest.raises(ValueError, match="non-empty and unique"):
        EvidenceClaim(EvidenceStatus.PASSED, NOW, ("contract://phase6", "contract://phase6"))
