import pytest

from data_source_harness.connector import Capability, ConnectorRegistry
from data_source_harness.models import QueryRequest
from data_source_harness.policy import (
    FieldRelationshipPolicy,
    PolicyDenied,
    QueryAccessGrant,
    RequestIdentity,
    StaticPolicy,
)
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


@pytest.mark.asyncio
async def test_gateway_enforces_field_and_relationship_grants_before_execution() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())
    policy = FieldRelationshipPolicy(
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        (
            QueryAccessGrant(
                "org",
                "solution",
                "agent",
                "lab.postgresql",
                {"orders": frozenset({"order_id"})},
            ),
        ),
    )
    gateway = HarnessGateway(registry, policy, MemoryTelemetrySink())
    allowed = QueryRequest(
        "lab.postgresql",
        ("orders",),
        {
            "select_by_asset": {"orders": ["order_id"]},
            "where_by_asset": {},
            "relationships": [],
        },
        10,
        1000,
        "test",
    )
    assert len([batch async for batch in gateway.execute(allowed, identity())]) == 1
    other_org = RequestIdentity(
        "other-org", "solution", "agent", "request-2", "trace-2", "sha256:policy"
    )
    with pytest.raises(PolicyDenied) as exc:
        _ = [batch async for batch in gateway.execute(allowed, other_org)]
    assert exc.value.decision.reason_code == "query_grant_missing"

    denied = QueryRequest(
        "lab.postgresql",
        ("orders",),
        {
            "select_by_asset": {"orders": ["customer_email"]},
            "where_by_asset": {},
            "relationships": [],
        },
        10,
        1000,
        "test",
    )
    with pytest.raises(PolicyDenied) as exc:
        _ = [batch async for batch in gateway.execute(denied, identity())]
    assert exc.value.decision.reason_code == "field_not_authorized"

    implicit_all_fields = QueryRequest(
        "lab.postgresql",
        ("orders",),
        {"select_by_asset": {}, "where_by_asset": {}, "relationships": []},
        10,
        1000,
        "test",
    )
    with pytest.raises(PolicyDenied) as exc:
        _ = [batch async for batch in gateway.execute(implicit_all_fields, identity())]
    assert exc.value.decision.reason_code == "query_shape_invalid"
