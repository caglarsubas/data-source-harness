from reference_labs.certify_phase6_5 import certify_phase6_5


async def test_phase6_5_integration_spine_certificate_passes() -> None:
    report = await certify_phase6_5()
    assert report.passed, report
    assert all(check.passed for check in report.checks)
    assert all(metric.passed for metric in report.metrics)
    assert "does not claim" in report.evidence_boundary
