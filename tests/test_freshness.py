from datetime import UTC, datetime, timedelta

import pytest

from data_source_harness.freshness import (
    CheckpointLedger,
    CheckpointRegression,
    FreshnessBreachAction,
    FreshnessObservation,
    FreshnessRegistry,
    FreshnessSLO,
)
from data_source_harness.models import CheckpointToken

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def test_freshness_slo_exposes_watermark_and_breach_action() -> None:
    registry = FreshnessRegistry()
    registry.record(FreshnessObservation("erp", "orders", NOW, NOW - timedelta(minutes=2), "42"))
    fresh = registry.assess("erp", "orders", FreshnessSLO(timedelta(minutes=5)), NOW)
    stale = registry.assess(
        "erp",
        "orders",
        FreshnessSLO(timedelta(minutes=1), FreshnessBreachAction.REFUSE),
        NOW,
    )
    assert fresh.fresh and fresh.watermark == "42"
    assert not stale.fresh and stale.action is FreshnessBreachAction.REFUSE


def test_checkpoint_resume_is_monotonic_and_version_bound() -> None:
    ledger = CheckpointLedger()
    ledger.record(CheckpointToken("events", "telemetry", "8", NOW, "1.0.0"))
    ledger.record(CheckpointToken("events", "telemetry", "9", NOW, "1.0.0"))
    assert ledger.resume("events", "telemetry").position == "9"  # type: ignore[union-attr]
    with pytest.raises(CheckpointRegression, match="regressed"):
        ledger.record(CheckpointToken("events", "telemetry", "7", NOW, "1.0.0"))
    with pytest.raises(CheckpointRegression, match="migration"):
        ledger.record(CheckpointToken("events", "telemetry", "10", NOW, "2.0.0"))
