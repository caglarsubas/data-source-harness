from datetime import UTC, datetime

import pytest

from data_source_harness.models import BatchKind, CheckpointToken, DataBatch


def test_batch_requires_lineage_and_source_version() -> None:
    with pytest.raises(ValueError, match="source version and lineage"):
        DataBatch(BatchKind.ARROW, [], (), ())


def test_source_timestamps_cannot_be_naive() -> None:
    from data_source_harness.models import SourceVersion

    with pytest.raises(ValueError, match="timezone-aware"):
        SourceVersion("erp", "1", datetime(2026, 8, 27))


def test_checkpoint_binds_position_to_connector_version() -> None:
    checkpoint = CheckpointToken("events", "orders", "partition-0:42", datetime.now(UTC), "0.1.0")
    assert checkpoint.position == "partition-0:42"
