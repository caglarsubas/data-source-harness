from __future__ import annotations

from reference_labs.certify_phase5 import certify_phase5
from reference_labs.cold_chain.phase5 import run_recovery_scenario as run_cold_chain
from reference_labs.white_goods.phase5 import run_recovery_scenario as run_white_goods


async def test_two_independent_labs_recover_without_duplicate_source_effects() -> None:
    for result in (await run_white_goods(), await run_cold_chain()):
        assert result.outcome_unknown
        assert result.blind_replay_blocked
        assert result.recovered
        assert result.restart_persisted
        assert result.one_source_effect
        assert result.journal_valid
        assert result.payload_free_journal


async def test_phase5_certificate_passes() -> None:
    report = await certify_phase5()
    assert report.passed, report
    assert len(report.metrics) == 10
