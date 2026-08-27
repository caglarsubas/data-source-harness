from __future__ import annotations

from reference_labs.certify_phase6 import certify_phase6


async def test_phase6_runtime_scaffold_certificate_passes() -> None:
    report = await certify_phase6()
    assert report.passed, report
    assert len(report.metrics) == 10
    assert "does not run real PostgreSQL" in report.evidence_boundary
