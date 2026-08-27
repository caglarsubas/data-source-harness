"""Connector ABI implementation backed by the hardened worker protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import datetime
from typing import Any

from .connector import ConnectorProfile, HealthStatus, UnsupportedCapability
from .deployment import EgressGuard
from .models import (
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
from .worker import ConnectorWorkerClient


class WorkerBackedConnector:
    """Translate canonical connector calls to ``harness.worker/v1`` messages."""

    def __init__(
        self,
        profile: ConnectorProfile,
        client: ConnectorWorkerClient,
        *,
        endpoint: str | None = None,
        egress_guard: EgressGuard | None = None,
    ) -> None:
        if profile.connector_id != client.spec.connector_id:
            raise ValueError("connector profile and worker connector identities must match")
        self._profile = profile
        self.client = client
        if (endpoint is None) != (egress_guard is None):
            raise ValueError("remote worker connectors require both endpoint and egress guard")
        self.endpoint = endpoint
        self.egress_guard = egress_guard

    @property
    def profile(self) -> ConnectorProfile:
        return self._profile

    async def health(self) -> HealthStatus:
        self._authorize_endpoint()
        result = await self.client.invoke("connector.health", {})
        return HealthStatus(
            bool(result.get("healthy")),
            str(result.get("observedVersion", "")),
            tuple(str(item) for item in result.get("limitations", ())),
        )

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        self._authorize_endpoint()
        result = await self.client.invoke("connector.discover", {"cursor": cursor})
        assets = result.get("assets")
        if not isinstance(assets, list):
            raise ValueError("worker discovery result must contain assets")
        if any(not isinstance(item, Mapping) for item in assets):
            raise ValueError("worker discovery assets must be structured")
        return tuple(
            Asset(
                AssetRef(self.profile.connector_id, str(item["assetId"])),
                str(item["name"]),
                str(item["kind"]),
                str(item["description"]) if item.get("description") is not None else None,
                dict(item.get("metadata", {})),
            )
            for item in assets
        )

    async def describe(self, asset: AssetRef) -> AssetSchema:
        self._authorize_endpoint()
        self._check_asset_source(asset)
        result = await self.client.invoke("connector.describe", {"assetId": asset.asset_id})
        fields = result.get("fields")
        if not isinstance(fields, list):
            raise ValueError("worker description must contain fields")
        if any(not isinstance(item, Mapping) for item in fields):
            raise ValueError("worker description fields must be structured")
        return AssetSchema(
            asset,
            tuple(
                FieldSchema(
                    str(item["name"]),
                    str(item["logicalType"]),
                    bool(item.get("nullable", True)),
                    str(item["description"]) if item.get("description") is not None else None,
                    dict(item.get("metadata", {})),
                )
                for item in fields
            ),
            self._version(result["version"]),
        )

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._authorize_endpoint()
        if request.source_id != self.profile.connector_id:
            raise ValueError("query source does not match worker connector")
        result = await self.client.invoke(
            "connector.query",
            {
                "sourceId": request.source_id,
                "assetIds": list(request.asset_ids),
                "plan": dict(request.plan),
                "limit": request.limit,
                "purpose": request.purpose,
                "policyAttributes": dict(request.policy_attributes),
            },
            timeout_seconds=request.deadline_ms / 1000,
        )
        batches = result.get("batches")
        if not isinstance(batches, list):
            raise ValueError("worker query result must contain batches")
        for item in batches:
            if not isinstance(item, Mapping):
                raise ValueError("worker batch must be structured")
            yield DataBatch(
                BatchKind(str(item["kind"])),
                item.get("payload"),
                tuple(self._version(value) for value in item.get("sourceVersions", ())),
                tuple(self._lineage(value) for value in item.get("lineage", ())),
                int(item["rowCount"]) if item.get("rowCount") is not None else None,
                int(item["byteCount"]) if item.get("byteCount") is not None else None,
            )

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        self._authorize_endpoint()
        if request.source_id != self.profile.connector_id:
            raise ValueError("search source does not match worker connector")
        result = await self.client.invoke(
            "connector.search",
            {
                "sourceId": request.source_id,
                "query": request.query,
                "topK": request.top_k,
                "filters": dict(request.filters),
                "purpose": request.purpose,
                "policyAttributes": dict(request.policy_attributes),
            },
        )
        hits = result.get("hits")
        if not isinstance(hits, list):
            raise ValueError("worker search result must contain hits")
        if any(not isinstance(item, Mapping) for item in hits):
            raise ValueError("worker search hits must be structured")
        return tuple(self._hit(item) for item in hits)

    async def subscribe(self, checkpoint: str | None = None) -> AsyncIterator[ChangeEvent]:
        raise UnsupportedCapability(self.profile.connector_id, self._capability("subscribe"))
        if False:  # pragma: no cover
            yield

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self._authorize_endpoint()
        return await self.client.invoke("connector.mutate", dict(request))

    async def checkpoint(self, stream_id: str) -> str:
        self._authorize_endpoint()
        result = await self.client.invoke("connector.checkpoint", {"streamId": stream_id})
        return str(result["checkpoint"])

    async def explain(self, request: QueryRequest) -> Mapping[str, Any]:
        self._authorize_endpoint()
        return await self.client.invoke(
            "connector.explain", {"assetIds": list(request.asset_ids), "plan": dict(request.plan)}
        )

    def _check_asset_source(self, asset: AssetRef) -> None:
        if asset.source_id != self.profile.connector_id:
            raise ValueError("asset source does not match worker connector")

    def _authorize_endpoint(self) -> None:
        if self.endpoint is not None and self.egress_guard is not None:
            self.egress_guard.authorize(self.endpoint)

    @staticmethod
    def _version(value: object) -> SourceVersion:
        if not isinstance(value, Mapping):
            raise ValueError("source version must be structured")
        return SourceVersion(
            str(value["sourceId"]),
            str(value["version"]),
            datetime.fromisoformat(str(value["observedAt"]).replace("Z", "+00:00")),
            datetime.fromisoformat(str(value["effectiveAt"]).replace("Z", "+00:00"))
            if value.get("effectiveAt")
            else None,
        )

    @staticmethod
    def _lineage(value: object) -> LineageRef:
        if not isinstance(value, Mapping):
            raise ValueError("lineage must be structured")
        return LineageRef(
            str(value["sourceId"]),
            str(value["assetId"]),
            str(value["recordId"]) if value.get("recordId") is not None else None,
            str(value["fieldPath"]) if value.get("fieldPath") is not None else None,
        )

    @classmethod
    def _hit(cls, value: Mapping[str, Any]) -> SearchHit:
        return SearchHit(
            str(value["sourceId"]),
            str(value["assetId"]),
            str(value["recordId"]),
            float(value["fusionScore"]),
            cls._version(value["sourceVersion"]),
            tuple(cls._lineage(item) for item in value.get("lineage", ())),
            lexical_score=cls._optional_float(value.get("lexicalScore")),
            dense_score=cls._optional_float(value.get("denseScore")),
            sparse_score=cls._optional_float(value.get("sparseScore")),
            reranker_score=cls._optional_float(value.get("rerankerScore")),
            acl_decision_id=str(value["aclDecisionId"])
            if value.get("aclDecisionId") is not None
            else None,
        )

    @staticmethod
    def _optional_float(value: object) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _capability(value: str) -> Any:
        from .connector import Capability

        return Capability(value)
