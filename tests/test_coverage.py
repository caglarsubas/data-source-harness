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
