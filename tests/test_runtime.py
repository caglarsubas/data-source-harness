import asyncio
from dataclasses import replace

import pytest

from data_source_harness.connector import Capability, ConnectorLimits, ConnectorRegistry
from data_source_harness.models import (
    BatchKind,
    DataBatch,
    LineageRef,
    QueryRequest,
    SearchHit,
    SearchRequest,
)
from data_source_harness.policy import (
    FieldRelationshipPolicy,
    PolicyDenied,
    QueryAccessGrant,
    RequestIdentity,
    StaticPolicy,
)
from data_source_harness.runtime import (
    ConnectorDeadlineExceeded,
    ConnectorResultViolation,
    HarnessGateway,
)
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


async def test_gateway_enforces_connector_result_byte_limit() -> None:
    connector = FakeConnector()
    connector._profile = replace(
        connector.profile,
        limits=ConnectorLimits(max_parallelism=1, max_result_bytes=1),
    )
    registry = ConnectorRegistry()
    registry.register(connector)
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    request = QueryRequest("lab.postgresql", ("orders",), {}, 10, 1_000, "test")
    with pytest.raises(ConnectorResultViolation, match="byte limit"):
        _ = [batch async for batch in gateway.execute(request, identity())]


async def test_gateway_enforces_query_deadline() -> None:
    class SlowConnector(FakeConnector):
        async def execute(self, request):
            await asyncio.sleep(0.05)
            async for batch in super().execute(request):
                yield batch

    registry = ConnectorRegistry()
    registry.register(SlowConnector())
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    request = QueryRequest("lab.postgresql", ("orders",), {}, 10, 1, "test")
    with pytest.raises(ConnectorDeadlineExceeded):
        _ = [batch async for batch in gateway.execute(request, identity())]


async def test_gateway_enforces_aggregate_row_limit_and_declared_count_truth() -> None:
    class RowConnector(FakeConnector):
        async def execute(self, request):
            yield DataBatch(
                BatchKind.ARROW,
                [{"order_id": "1"}, {"order_id": "2"}],
                (self.version,),
                (self.lineage,),
                row_count=2,
            )

    registry = ConnectorRegistry()
    registry.register(RowConnector())
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    request = QueryRequest("lab.postgresql", ("orders",), {}, 1, 1_000, "test")
    with pytest.raises(ConnectorResultViolation, match="more rows"):
        _ = [batch async for batch in gateway.execute(request, identity())]

    class LyingRowConnector(RowConnector):
        async def execute(self, request):
            yield DataBatch(
                BatchKind.ARROW,
                [{"order_id": "1"}],
                (self.version,),
                (self.lineage,),
                row_count=2,
            )

    other_registry = ConnectorRegistry()
    other_registry.register(LyingRowConnector())
    other_gateway = HarnessGateway(
        other_registry,
        StaticPolicy({("lab.postgresql", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    with pytest.raises(ConnectorResultViolation, match="does not match"):
        _ = [batch async for batch in other_gateway.execute(request, identity())]


async def test_gateway_bounds_and_times_out_complete_search_results() -> None:
    class SearchConnector(FakeConnector):
        def __init__(self, *, slow: bool = False, max_bytes: int = 10_000) -> None:
            super().__init__()
            self.slow = slow
            self._profile = replace(
                self.profile,
                capabilities=self.profile.capabilities | {Capability.SEARCH},
                limits=ConnectorLimits(max_parallelism=1, max_result_bytes=max_bytes),
            )

        async def search(self, request):
            if self.slow:
                await asyncio.sleep(0.05)
            return (
                SearchHit(
                    self.profile.connector_id,
                    "orders-index",
                    "order-1",
                    1.0,
                    self.version,
                    (
                        LineageRef(
                            self.profile.connector_id,
                            "orders",
                            "order-1",
                            "x" * 1_000,
                        ),
                    ),
                    acl_decision_id="acl:1",
                ),
            )

    def search_gateway(connector: SearchConnector) -> HarnessGateway:
        registry = ConnectorRegistry()
        registry.register(connector)
        return HarnessGateway(
            registry,
            StaticPolicy({("lab.postgresql", Capability.SEARCH)}),
            MemoryTelemetrySink(),
        )

    request = SearchRequest("lab.postgresql", "order", 1, deadline_ms=1_000)
    with pytest.raises(ConnectorResultViolation, match="byte limit"):
        await search_gateway(SearchConnector(max_bytes=100)).search(request, identity())
    with pytest.raises(ConnectorDeadlineExceeded):
        await search_gateway(SearchConnector(slow=True)).search(
            replace(request, deadline_ms=1), identity()
        )


def test_search_hit_rejects_non_finite_scores() -> None:
    connector = FakeConnector()
    with pytest.raises(ValueError, match="finite"):
        SearchHit(
            connector.profile.connector_id,
            "orders-index",
            "order-1",
            float("nan"),
            connector.version,
            (connector.lineage,),
            acl_decision_id="acl:1",
        )
