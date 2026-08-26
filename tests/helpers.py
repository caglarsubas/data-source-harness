from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any

from data_source_harness.connector import (
    Capability,
    ConnectorProfile,
    DataModel,
    HealthStatus,
    RuntimeMode,
)
from data_source_harness.models import (
    Asset,
    AssetRef,
    AssetSchema,
    BatchKind,
    ChangeEvent,
    DataBatch,
    FieldSchema,
    LineageRef,
    QueryRequest,
    SearchHit,
    SearchRequest,
    SourceVersion,
)

NOW = datetime(2026, 8, 27, tzinfo=UTC)


class FakeConnector:
    def __init__(self, connector_id: str = "lab.postgresql") -> None:
        self._profile = ConnectorProfile(
            connector_id=connector_id,
            version="0.1.0",
            sdk_api="harness.connector/v1",
            runtime_mode=RuntimeMode.PROCESS,
            data_models=frozenset({DataModel.TABULAR}),
            capabilities=frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
            auth_methods=frozenset({"credential_reference"}),
        )
        self.asset = Asset(AssetRef(connector_id, "orders"), "orders", "table")
        self.version = SourceVersion(connector_id, "watermark:42", NOW)
        self.lineage = LineageRef(connector_id, "orders", "order-1")

    @property
    def profile(self) -> ConnectorProfile:
        return self._profile

    async def health(self) -> HealthStatus:
        return HealthStatus(True, self.profile.version)

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        return (self.asset,)

    async def describe(self, asset: AssetRef) -> AssetSchema:
        return AssetSchema(asset, (FieldSchema("order_id", "string", False),), self.version)

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        yield DataBatch(
            BatchKind.ARROW,
            [{"order_id": "order-1"}],
            (self.version,),
            (self.lineage,),
            row_count=1,
        )

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        return ()

    async def subscribe(self, checkpoint: str | None = None) -> AsyncIterator[ChangeEvent]:
        if False:
            yield

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"status": "not-enabled"}

    async def checkpoint(self, stream_id: str) -> str:
        return "42"

    async def explain(self, request: QueryRequest) -> Mapping[str, Any]:
        return {"plan": "scan"}
