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
    assert "creates no cloud resources" in report.evidence_boundary


def test_phase7_snapshot_records_read_only_observations() -> None:
    campaign = build_readiness_campaign()
    assert campaign.cost_boundary.provisioning_authorized is False
    assert campaign.cost_boundary.resources_created == ()
    assert campaign.cost_boundary.external_mutations == ()
    assert len(campaign.evidence) == 9
    assert not campaign.accepted
