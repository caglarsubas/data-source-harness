import asyncio
from datetime import UTC, datetime

import pytest

from data_source_harness.connector import Capability, ConnectorRegistry
from data_source_harness.coordination import (
    CrossSourceCoordinator,
    QueryStep,
    SourceExecutionPlan,
)
from data_source_harness.models import QueryRequest
from data_source_harness.policy import RequestIdentity, StaticPolicy
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink

from .helpers import FakeConnector

NOW = datetime(2026, 8, 27, tzinfo=UTC)


def identity() -> RequestIdentity:
    return RequestIdentity("org", "solution", "agent", "coord-1", "trace", "policy:v1")


def query(source_id: str) -> QueryRequest:
    return QueryRequest(source_id, ("orders",), {}, 10, 1_000, "coordinated test")


async def test_coordinator_derives_complete_coverage_and_deduplicated_lineage() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector("erp"))
    registry.register(FakeConnector("warehouse"))
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("erp", Capability.QUERY), ("warehouse", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    result = await CrossSourceCoordinator(gateway).execute(
        SourceExecutionPlan(
            "coord-1",
            NOW,
            (QueryStep("erp", query("erp")), QueryStep("warehouse", query("warehouse"))),
        ),
        identity(),
    )
    assert result.complete
    assert result.coverage.expected_sources == frozenset({"erp", "warehouse"})
    assert {item.source_id for item in result.lineage} == {"erp", "warehouse"}


async def test_coordinator_exposes_failed_source_without_overstating_coverage() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector("erp"))
    registry.register(FakeConnector("warehouse"))
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("erp", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    result = await CrossSourceCoordinator(gateway).execute(
        SourceExecutionPlan(
            "coord-1",
            NOW,
            (QueryStep("erp", query("erp")), QueryStep("warehouse", query("warehouse"))),
        ),
        identity(),
    )
    assert not result.complete
    assert result.coverage.excluded[0].source_id == "warehouse"
    assert result.coverage.excluded[0].reason_code == "source_execution_failed"


async def test_coordinator_propagates_caller_cancellation() -> None:
    class SlowConnector(FakeConnector):
        async def execute(self, request):
            await asyncio.sleep(10)
            async for batch in super().execute(request):
                yield batch

    registry = ConnectorRegistry()
    registry.register(SlowConnector("erp"))
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("erp", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    task = asyncio.create_task(
        CrossSourceCoordinator(gateway).execute(
            SourceExecutionPlan("coord-1", NOW, (QueryStep("erp", query("erp")),)),
            identity(),
        )
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
