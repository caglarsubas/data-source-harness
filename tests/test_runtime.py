import pytest

from data_source_harness.connector import Capability, ConnectorRegistry
from data_source_harness.models import QueryRequest
from data_source_harness.policy import PolicyDenied, RequestIdentity, StaticPolicy
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink

from .helpers import FakeConnector


def identity() -> RequestIdentity:
    return RequestIdentity("org", "solution", "agent", "request", "trace", "sha256:policy")


@pytest.mark.asyncio
async def test_gateway_authorizes_locally_and_emits_neutral_evidence() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())
    telemetry = MemoryTelemetrySink()
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        telemetry,
    )
    request = QueryRequest(
        "lab.postgresql", ("orders",), {"select": ["order_id"]}, 10, 1000, "test"
    )
    batches = [batch async for batch in gateway.execute(request, identity())]
    assert batches[0].row_count == 1
    assert [event.name for event in telemetry.events] == [
        "data.harness.authorization.decided",
        "data.harness.batch.emitted",
    ]


@pytest.mark.asyncio
async def test_gateway_denies_before_connector_execution() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())
    gateway = HarnessGateway(registry, StaticPolicy(set()), MemoryTelemetrySink())
    request = QueryRequest("lab.postgresql", ("orders",), {}, 10, 1000, "test")
    with pytest.raises(PolicyDenied):
        _ = [batch async for batch in gateway.execute(request, identity())]
