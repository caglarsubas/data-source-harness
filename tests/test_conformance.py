import pytest

from data_source_harness.conformance import run_connector_conformance

from .helpers import FakeConnector


@pytest.mark.asyncio
async def test_reference_connector_passes_foundation_conformance() -> None:
    report = await run_connector_conformance(FakeConnector())
    assert report.passed
    assert {check.check_id for check in report.checks} == {
        "profile.valid",
        "health.healthy",
        "discovery.deterministic",
        "discovery.unique_identity",
        "describe.matches_asset",
    }
