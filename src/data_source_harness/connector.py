"""Capability-negotiated connector contract and registry."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .models import (
    Asset,
    AssetRef,
    AssetSchema,
    ChangeEvent,
    DataBatch,
    QueryRequest,
    SearchHit,
    SearchRequest,
)


class Capability(StrEnum):
    DISCOVER = "discover"
    DESCRIBE = "describe"
    QUERY = "query"
    SCAN = "scan"
    SEARCH = "search"
    SUBSCRIBE = "subscribe"
    MUTATE = "mutate"
    TRANSACTION = "transaction"
    CDC = "cdc"
    EXPLAIN = "explain"
    PREDICATE_PUSHDOWN = "predicate_pushdown"
    PROJECTION_PUSHDOWN = "projection_pushdown"


class DataModel(StrEnum):
    TABULAR = "tabular"
    DOCUMENT = "document"
    GRAPH = "graph"
    EVENT = "event"
    BINARY = "binary"
    VECTOR = "vector"


class RuntimeMode(StrEnum):
    PROCESS = "process"
    CONTAINER = "container"
    WASM = "wasm"
    REMOTE = "remote"


class UnsupportedCapability(RuntimeError):
    def __init__(self, connector_id: str, capability: Capability) -> None:
        super().__init__(f"connector {connector_id!r} does not support {capability.value!r}")
        self.connector_id = connector_id
        self.capability = capability


@dataclass(frozen=True)
class ConsistencyProfile:
    read_isolation: tuple[str, ...] = ("eventual",)
    change_delivery: str | None = None
    supports_version_precondition: bool = False
    supports_idempotency_key: bool = False
    supports_transactions: bool = False
    supports_checkpoint: bool = False
    supports_cdc: bool = False


@dataclass(frozen=True)
class ConnectorLimits:
    max_parallelism: int = 1
    max_result_bytes: int = 10 * 1024 * 1024
    supports_cancellation: bool = True

    def __post_init__(self) -> None:
        if self.max_parallelism <= 0 or self.max_result_bytes <= 0:
            raise ValueError("connector limits must be positive")


@dataclass(frozen=True)
class ConnectorProfile:
    connector_id: str
    version: str
    sdk_api: str
    runtime_mode: RuntimeMode
    data_models: frozenset[DataModel]
    capabilities: frozenset[Capability]
    auth_methods: frozenset[str]
    consistency: ConsistencyProfile = field(default_factory=ConsistencyProfile)
    limits: ConnectorLimits = field(default_factory=ConnectorLimits)
    extension_namespace: str | None = None
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.connector_id or not self.version:
            raise ValueError("connector_id and version are required")
        if self.sdk_api != "harness.connector/v1":
            raise ValueError(f"unsupported connector sdk_api: {self.sdk_api!r}")
        if Capability.DISCOVER not in self.capabilities:
            raise ValueError("all connectors must support discovery")
        if Capability.DESCRIBE not in self.capabilities:
            raise ValueError("all connectors must support schema description")
        if not self.data_models:
            raise ValueError("at least one data model is required")
        if not self.auth_methods:
            raise ValueError("at least one credential-reference authentication method is required")
        if (
            Capability.TRANSACTION in self.capabilities
            and not self.consistency.supports_transactions
        ):
            raise ValueError("transaction capability contradicts consistency profile")
        if Capability.CDC in self.capabilities and not self.consistency.supports_cdc:
            raise ValueError("CDC capability contradicts consistency profile")


@dataclass(frozen=True)
class HealthStatus:
    healthy: bool
    observed_version: str
    limitations: tuple[str, ...] = ()


@runtime_checkable
class Connector(Protocol):
    @property
    def profile(self) -> ConnectorProfile: ...

    async def health(self) -> HealthStatus: ...

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]: ...

    async def describe(self, asset: AssetRef) -> AssetSchema: ...

    def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]: ...

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]: ...

    def subscribe(self, checkpoint: str | None = None) -> AsyncIterator[ChangeEvent]: ...

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...

    async def checkpoint(self, stream_id: str) -> str: ...

    async def explain(self, request: QueryRequest) -> Mapping[str, Any]: ...


class ConnectorRegistry:
    """In-memory registry with immutable connector identities per process."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        profile = connector.profile
        if profile.connector_id in self._connectors:
            raise ValueError(f"connector already registered: {profile.connector_id}")
        self._connectors[profile.connector_id] = connector

    def get(self, connector_id: str, capability: Capability | None = None) -> Connector:
        try:
            connector = self._connectors[connector_id]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {connector_id}") from exc
        if capability is not None and capability not in connector.profile.capabilities:
            raise UnsupportedCapability(connector_id, capability)
        return connector

    def profiles(self) -> tuple[ConnectorProfile, ...]:
        return tuple(
            self._connectors[connector_id].profile for connector_id in sorted(self._connectors)
        )
