from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from data_source_harness.acceptance import (
    REQUIRED_ACCEPTANCE_COMPONENTS,
    AcceptanceStage,
    CostBoundary,
    LiveAcceptanceCampaign,
    LiveSourceShape,
    LiveSourceTarget,
    ReleaseArtifact,
    StageEvidence,
)
from data_source_harness.evidence import EvidenceStatus

NOW = datetime(2026, 8, 28, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
REVISIONS = {
    "data-source-harness": "1" * 40,
    "ADLC": "2" * 40,
    "Python-SDK": "3" * 40,
    "OCP-reference-lab": "4" * 40,
    "model-plane": "5" * 40,
}


def artifacts(*, resolved: bool) -> tuple[ReleaseArtifact, ...]:
    return tuple(
        ReleaseArtifact(
            component,
            f"https://example.test/{component}",
            revision,
            DIGEST if resolved else None,
        )
        for component, revision in REVISIONS.items()
    )


def sources(*, verified: bool) -> tuple[LiveSourceTarget, ...]:
    return tuple(
        LiveSourceTarget(
            f"source-{shape.value}",
            shape,
            f"connector-{shape.value}",
            f"credential-ref://phase7/{shape.value}",
            DIGEST if verified else None,
            verified,
            NOW if verified else None,
            (f"evidence://{shape.value}",) if verified else (),
        )
        for shape in LiveSourceShape
    )


def all_passed_evidence() -> tuple[StageEvidence, ...]:
    return tuple(
        StageEvidence(
            component,
            stage,
            EvidenceStatus.PASSED,
            REVISIONS[component],
            DIGEST,
            NOW,
            (f"evidence://{component}/{stage.value}",),
        )
        for component in sorted(REQUIRED_ACCEPTANCE_COMPONENTS)
        for stage in AcceptanceStage
    )


def test_complete_campaign_requires_every_bound_stage_and_live_source() -> None:
    campaign = LiveAcceptanceCampaign(
        "phase7-complete",
        "release-set-1",
        NOW,
        artifacts(resolved=True),
        sources(verified=True),
        all_passed_evidence(),
    )
    contract = campaign.to_contract()
    assert campaign.accepted
    assert campaign.blockers == ()
    assert contract["accepted"] is True
    assert len(contract["evidence"]) == 55
    assert contract["releaseSetDigest"].startswith("sha256:")


def test_partial_campaign_preserves_every_missing_gate_as_a_blocker() -> None:
    campaign = LiveAcceptanceCampaign(
        "phase7-readiness",
        "release-set-1",
        NOW,
        artifacts(resolved=False),
        sources(verified=False),
        (
            StageEvidence(
                "data-source-harness",
                AcceptanceStage.SOURCE,
                EvidenceStatus.PASSED,
                REVISIONS["data-source-harness"],
                None,
                NOW,
                ("https://example.test/commit",),
            ),
        ),
    )
    assert not campaign.accepted
    assert "Python-SDK:exact-main-ci:missing" in campaign.blockers
    assert "source-rest:live-verification-missing" in campaign.blockers
    assert "model-plane:artifact-digest-missing" in campaign.blockers
    assert campaign.to_contract()["costBoundary"]["resourcesCreated"] == []


def test_deployment_evidence_cannot_omit_or_change_artifact_identity() -> None:
    with pytest.raises(ValueError, match="must bind an artifact digest"):
        StageEvidence(
            "ADLC",
            AcceptanceStage.DEPLOYMENT,
            EvidenceStatus.PASSED,
            REVISIONS["ADLC"],
            None,
            NOW,
            ("evidence://deployment",),
        )

    evidence = StageEvidence(
        "ADLC",
        AcceptanceStage.SOURCE,
        EvidenceStatus.PASSED,
        REVISIONS["ADLC"],
        DIGEST,
        NOW,
        ("evidence://source",),
    )
    with pytest.raises(ValueError, match="artifact digest does not match"):
        LiveAcceptanceCampaign(
            "phase7-mismatch",
            "release-set-1",
            NOW,
            artifacts(resolved=False),
            sources(verified=False),
            (evidence,),
        )


def test_live_sources_and_cost_boundary_fail_closed() -> None:
    with pytest.raises(ValueError, match="credential references"):
        LiveSourceTarget(
            "postgres",
            LiveSourceShape.POSTGRESQL,
            "connector",
            "https://db.example.test",
        )
    with pytest.raises(ValueError, match="credential references"):
        LiveSourceTarget(
            "postgres",
            LiveSourceShape.POSTGRESQL,
            "connector",
            "credential-ref://",
        )
    with pytest.raises(ValueError, match="require image digest"):
        LiveSourceTarget(
            "postgres",
            LiveSourceShape.POSTGRESQL,
            "connector",
            "credential-ref://phase7/postgres",
            live_verified=True,
            observed_at=NOW,
            references=("evidence://postgres",),
        )
    with pytest.raises(ValueError, match="unauthorized campaign"):
        CostBoundary(False, ("gcp://new-cluster",), ())


def test_release_set_digest_is_order_independent() -> None:
    first = LiveAcceptanceCampaign(
        "phase7-a",
        "release-set-1",
        NOW,
        artifacts(resolved=False),
        sources(verified=False),
        (),
    )
    second = LiveAcceptanceCampaign(
        "phase7-b",
        "release-set-1",
        NOW,
        tuple(reversed(artifacts(resolved=False))),
        tuple(reversed(sources(verified=False))),
        (),
    )
    assert first.release_set_digest == second.release_set_digest


def test_contract_parser_recomputes_acceptance_and_blockers() -> None:
    campaign = LiveAcceptanceCampaign(
        "phase7-readiness",
        "release-set-1",
        NOW,
        artifacts(resolved=False),
        sources(verified=False),
        (),
    )
    contract = campaign.to_contract()
    assert LiveAcceptanceCampaign.from_contract(contract) == campaign
    contract["accepted"] = True
    contract["blockers"] = []
    with pytest.raises(ValueError, match="declared acceptance"):
        LiveAcceptanceCampaign.from_contract(contract)


def test_release_artifact_identity_guards() -> None:
    with pytest.raises(ValueError, match="component"):
        ReleaseArtifact("", "https://example.test/repo", "1" * 40)
    with pytest.raises(ValueError, match="HTTPS"):
        ReleaseArtifact("ADLC", "git@example.test:repo", "1" * 40)
    with pytest.raises(ValueError, match="exact Git SHA"):
        ReleaseArtifact("ADLC", "https://example.test/repo", "main")
    with pytest.raises(ValueError, match="sha256"):
        ReleaseArtifact("ADLC", "https://example.test/repo", "1" * 40, "sha256:no")


def test_observation_validation_rejects_ambiguous_evidence() -> None:
    with pytest.raises(ValueError, match="identities"):
        LiveSourceTarget("", LiveSourceShape.REST, "connector", "credential-ref://x/y")
    with pytest.raises(ValueError, match="timezone-aware"):
        LiveSourceTarget(
            "rest",
            LiveSourceShape.REST,
            "connector",
            "credential-ref://x/y",
            DIGEST,
            True,
            datetime(2026, 8, 28),
            ("evidence://rest",),
        )
    with pytest.raises(ValueError, match="cannot carry observations"):
        LiveSourceTarget(
            "rest",
            LiveSourceShape.REST,
            "connector",
            "credential-ref://x/y",
            observed_at=NOW,
        )
    with pytest.raises(ValueError, match="observed pass or failure"):
        StageEvidence(
            "ADLC",
            AcceptanceStage.SOURCE,
            EvidenceStatus.MISSING,
            REVISIONS["ADLC"],
            None,
            NOW,
            ("evidence://source",),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        StageEvidence(
            "ADLC",
            AcceptanceStage.SOURCE,
            EvidenceStatus.PASSED,
            REVISIONS["ADLC"],
            None,
            datetime(2026, 8, 28),
            ("evidence://source",),
        )
    with pytest.raises(ValueError, match="non-empty and unique"):
        StageEvidence(
            "ADLC",
            AcceptanceStage.SOURCE,
            EvidenceStatus.PASSED,
            REVISIONS["ADLC"],
            None,
            NOW,
            ("evidence://source", "evidence://source"),
        )


def test_campaign_identity_and_matrix_guards() -> None:
    base_artifacts = artifacts(resolved=False)
    base_sources = sources(verified=False)
    with pytest.raises(ValueError, match="identities"):
        LiveAcceptanceCampaign("", "release", NOW, base_artifacts, base_sources, ())
    with pytest.raises(ValueError, match="timezone-aware"):
        LiveAcceptanceCampaign(
            "campaign", "release", datetime(2026, 8, 28), base_artifacts, base_sources, ()
        )
    with pytest.raises(ValueError, match="five platform"):
        LiveAcceptanceCampaign("campaign", "release", NOW, base_artifacts[:-1], base_sources, ())
    with pytest.raises(ValueError, match="four unique"):
        LiveAcceptanceCampaign(
            "campaign", "release", NOW, base_artifacts, base_sources[:-1] + (base_sources[0],), ()
        )

    source = StageEvidence(
        "ADLC",
        AcceptanceStage.SOURCE,
        EvidenceStatus.PASSED,
        REVISIONS["ADLC"],
        None,
        NOW,
        ("evidence://source",),
    )
    with pytest.raises(ValueError, match="must be unique"):
        LiveAcceptanceCampaign(
            "campaign", "release", NOW, base_artifacts, base_sources, (source, source)
        )
    with pytest.raises(ValueError, match="revision does not match"):
        LiveAcceptanceCampaign(
            "campaign",
            "release",
            NOW,
            base_artifacts,
            base_sources,
            (replace(source, revision="f" * 40),),
        )


def test_failed_observation_and_contract_tampering_remain_visible() -> None:
    failed = StageEvidence(
        "ADLC",
        AcceptanceStage.SOURCE,
        EvidenceStatus.FAILED,
        REVISIONS["ADLC"],
        None,
        NOW,
        ("evidence://failed",),
    )
    campaign = LiveAcceptanceCampaign(
        "campaign", "release", NOW, artifacts(resolved=False), sources(verified=False), (failed,)
    )
    assert "ADLC:source:failed" in campaign.blockers
    for field, value, message in (
        ("schemaVersion", "other/v1", "schema version"),
        ("releaseSetDigest", DIGEST, "release-set digest"),
        ("blockers", [], "declared blockers"),
    ):
        contract = campaign.to_contract()
        contract[field] = value
        with pytest.raises(ValueError, match=message):
            LiveAcceptanceCampaign.from_contract(contract)


def test_authorized_cost_boundary_still_rejects_duplicate_entries() -> None:
    assert CostBoundary(True, ("gcp://cluster",), ("deploy://runtime",)).provisioning_authorized
    with pytest.raises(ValueError, match="non-empty and unique"):
        CostBoundary(True, ("gcp://cluster", "gcp://cluster"), ())
