from __future__ import annotations

import pytest

from reference_labs.certify_phase4 import certify_phase4
from reference_labs.cold_chain.phase4 import run_action_scenario as run_cold_chain
from reference_labs.white_goods.phase4 import run_action_scenario as run_white_goods
from reference_labs.white_goods.phase4 import run_saga_scenario


@pytest.mark.asyncio
async def test_white_goods_action_safety_and_compensation() -> None:
    result = await run_white_goods()
    assert result.previewed
    assert result.unauthorized_denied
    assert result.approval_denied
    assert result.idempotent
    assert result.compensated
    assert result.audit_valid and result.payload_free_audit


@pytest.mark.asyncio
async def test_cold_chain_action_safety_and_compensation() -> None:
    result = await run_cold_chain()
    assert result.previewed
    assert result.precondition_denied
    assert result.idempotent
    assert result.compensated
    assert result.audit_valid and result.payload_free_audit


@pytest.mark.asyncio
async def test_phase4_certificate_passes() -> None:
    report = await certify_phase4()
    assert report.passed
    assert len(report.labs) == 2
    assert len(report.metrics) == 10


@pytest.mark.asyncio
async def test_white_goods_saga_compensates_after_later_failure() -> None:
    assert await run_saga_scenario()
