from reference_labs.certify_phase7_readiness import (
    build_readiness_campaign,
    certify_phase7_readiness,
)


async def test_phase7_readiness_passes_without_claiming_live_acceptance() -> None:
    report = await certify_phase7_readiness()
    assert report.passed, report
    assert report.campaign_accepted is False
    assert all(check.passed for check in report.checks)
    assert all(metric.passed for metric in report.metrics)
    assert "Python-SDK:exact-main-ci:missing" in report.blockers
    assert "four digest-bound source services" in report.evidence_boundary
    assert "revision-bound SDK receipt" in report.evidence_boundary
    assert any(check.check_id == "campaign.local-cross-plane-evidence" for check in report.checks)
    assert any(
        check.check_id == "campaign.local-harness-runtime-evidence" for check in report.checks
    )
    assert not any("live-verification-missing" in blocker for blocker in report.blockers)
    assert "data-source-harness:runtime:missing" not in report.blockers
    assert len(report.blockers) == 38


def test_phase7_snapshot_records_read_only_observations() -> None:
    campaign = build_readiness_campaign()
    assert campaign.cost_boundary.provisioning_authorized is False
    assert campaign.cost_boundary.resources_created == ()
    assert campaign.cost_boundary.external_mutations == ()
    assert len(campaign.evidence) == 9
    assert all(source.live_verified for source in campaign.sources)
    assert not campaign.accepted
