from datetime import UTC, datetime

import pytest

from data_source_harness.coverage import CoverageExclusion, CoverageStatement, SourceCoverage


def test_partial_coverage_is_explicit_and_not_complete() -> None:
    statement = CoverageStatement(
        "req-1",
        datetime.now(UTC),
        (SourceCoverage("erp", ("orders",), True),),
        (CoverageExclusion("legacy", "unavailable", "maintenance"),),
    )
    assert not statement.is_complete


def test_source_cannot_be_included_and_excluded() -> None:
    with pytest.raises(ValueError, match="both included and excluded"):
        CoverageStatement(
            "req-1",
            datetime.now(UTC),
            (SourceCoverage("erp", ("orders",), True),),
            (CoverageExclusion("erp", "denied", "policy"),),
        )


def test_expected_source_universe_prevents_silent_omissions() -> None:
    statement = CoverageStatement(
        "req-1",
        datetime.now(UTC),
        (SourceCoverage("erp", ("orders",), True),),
        expected_sources=frozenset({"erp", "telemetry"}),
    )
    assert not statement.is_complete


def test_coverage_models_reject_incomplete_and_ambiguous_shapes() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="reason and detail"):
        CoverageExclusion("erp", "", "missing")
    with pytest.raises(ValueError, match="source and at least one asset"):
        SourceCoverage("erp", (), True)
    with pytest.raises(ValueError, match="unique"):
        SourceCoverage("erp", ("orders", "orders"), True)
    with pytest.raises(ValueError, match="request_id"):
        CoverageStatement("", now, (SourceCoverage("erp", ("orders",), True),))
    with pytest.raises(ValueError, match="timezone-aware"):
        CoverageStatement(
            "req",
            datetime(2026, 8, 27),
            (SourceCoverage("erp", ("orders",), True),),
        )
    with pytest.raises(ValueError, match="include or exclude"):
        CoverageStatement("req", now, ())
    with pytest.raises(ValueError, match="only once"):
        CoverageStatement(
            "req",
            now,
            (
                SourceCoverage("erp", ("orders",), True),
                SourceCoverage("erp", ("products",), True),
            ),
        )
    with pytest.raises(ValueError, match="non-empty"):
        CoverageStatement(
            "req",
            now,
            (SourceCoverage("erp", ("orders",), True),),
            expected_sources=frozenset({""}),
        )
    with pytest.raises(ValueError, match="outside"):
        CoverageStatement(
            "req",
            now,
            (SourceCoverage("erp", ("orders",), True),),
            expected_sources=frozenset({"warehouse"}),
        )
