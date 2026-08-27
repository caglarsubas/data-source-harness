"""Policy-enforcing gateway for connector execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping

from .connector import Capability, ConnectorRegistry
from .models import Asset, DataBatch, QueryRequest, Scalar, SearchHit, SearchRequest
from .policy import AuthorizationRequest, PolicyDenied, PolicyEvaluator, RequestIdentity
from .telemetry import TelemetryEvent, TelemetrySink


class ConnectorDeadlineExceeded(TimeoutError):
    pass


class ConnectorResultViolation(RuntimeError):
    pass


class HarnessGateway:
    """Executes locally; no control-plane network call exists in this path."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        policy: PolicyEvaluator,
        telemetry: TelemetrySink,
    ) -> None:
        self.registry = registry
        self.policy = policy
        self.telemetry = telemetry
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    async def discover(self, source_id: str, identity: RequestIdentity) -> tuple[Asset, ...]:
        connector = self.registry.get(source_id, Capability.DISCOVER)
        await self._authorize(
            identity, source_id, Capability.DISCOVER, (), "asset discovery", {}, {}
        )
        assets = await connector.discover()
        await self.telemetry.emit(
            TelemetryEvent(
                "data.harness.discovery.completed",
                identity,
                attributes={"source_id": source_id, "asset_count": len(assets)},
            )
        )
        return assets

    async def execute(
        self, request: QueryRequest, identity: RequestIdentity
    ) -> AsyncIterator[DataBatch]:
        connector = self.registry.get(request.source_id, Capability.QUERY)
        await self._authorize(
            identity,
            request.source_id,
            Capability.QUERY,
            request.asset_ids,
            request.purpose,
            request.policy_attributes,
            request.plan,
        )
        total_bytes = 0
        total_rows = 0
        try:
            async with self._semaphore(connector.profile.connector_id):
                async with asyncio.timeout(request.deadline_ms / 1000):
                    async for batch in connector.execute(request):
                        batch_bytes = self._batch_bytes(batch)
                        total_bytes += batch_bytes
                        total_rows += self._batch_rows(batch)
                        if total_bytes > connector.profile.limits.max_result_bytes:
                            raise ConnectorResultViolation(
                                "connector result exceeds its declared byte limit"
                            )
                        if total_rows > request.limit:
                            raise ConnectorResultViolation(
                                "connector returned more rows than requested"
                            )
                        if not any(
                            version.source_id == request.source_id
                            for version in batch.source_versions
                        ):
                            raise ConnectorResultViolation(
                                "connector batch does not carry its source version"
                            )
                        await self.telemetry.emit(
                            TelemetryEvent(
                                "data.harness.batch.emitted",
                                identity,
                                attributes={
                                    "source_id": request.source_id,
                                    "kind": batch.kind.value,
                                    "row_count": batch.row_count,
                                    "byte_count": batch_bytes,
                                },
                            )
                        )
                        yield batch
        except TimeoutError as exc:
            raise ConnectorDeadlineExceeded(
                f"connector deadline exceeded: {request.source_id}"
            ) from exc

    async def search(
        self, request: SearchRequest, identity: RequestIdentity
    ) -> tuple[SearchHit, ...]:
        connector = self.registry.get(request.source_id, Capability.SEARCH)
        await self._authorize(
            identity,
            request.source_id,
            Capability.SEARCH,
            (),
            request.purpose,
            request.policy_attributes,
            request.filters,
        )
        try:
            async with self._semaphore(connector.profile.connector_id):
                async with asyncio.timeout(request.deadline_ms / 1000):
                    hits = await connector.search(request)
        except TimeoutError as exc:
            raise ConnectorDeadlineExceeded(
                f"connector deadline exceeded: {request.source_id}"
            ) from exc
        if len(hits) > request.top_k:
            raise ConnectorResultViolation("connector returned more search hits than requested")
        if any(
            hit.source_id != request.source_id
            or hit.source_version.source_id != request.source_id
            or not hit.acl_decision_id
            for hit in hits
        ):
            raise ConnectorResultViolation(
                "search results require matching source/version identity and ACL evidence"
            )
        try:
            serialized = json.dumps(
                [
                    {
                        "sourceId": hit.source_id,
                        "assetId": hit.asset_id,
                        "recordId": hit.record_id,
                        "fusionScore": hit.fusion_score,
                        "lexicalScore": hit.lexical_score,
                        "denseScore": hit.dense_score,
                        "sparseScore": hit.sparse_score,
                        "rerankerScore": hit.reranker_score,
                        "sourceVersion": {
                            "sourceId": hit.source_version.source_id,
                            "version": hit.source_version.version,
                            "observedAt": hit.source_version.observed_at.isoformat(),
                            "effectiveAt": hit.source_version.effective_at.isoformat()
                            if hit.source_version.effective_at
                            else None,
                        },
                        "lineage": [
                            {
                                "sourceId": item.source_id,
                                "assetId": item.asset_id,
                                "recordId": item.record_id,
                                "fieldPath": item.field_path,
                            }
                            for item in hit.lineage
                        ],
                        "aclDecisionId": hit.acl_decision_id,
                    }
                    for hit in hits
                ],
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ConnectorResultViolation("search result is not finite JSON") from exc
        if len(serialized) > connector.profile.limits.max_result_bytes:
            raise ConnectorResultViolation("search result exceeds connector byte limit")
        await self.telemetry.emit(
            TelemetryEvent(
                "data.harness.search.completed",
                identity,
                attributes={
                    "source_id": request.source_id,
                    "candidate_count": len(hits),
                },
            )
        )
        return hits

    def _semaphore(self, source_id: str) -> asyncio.Semaphore:
        semaphore = self._semaphores.get(source_id)
        if semaphore is None:
            connector = self.registry.get(source_id)
            semaphore = asyncio.Semaphore(connector.profile.limits.max_parallelism)
            self._semaphores[source_id] = semaphore
        return semaphore

    @staticmethod
    def _batch_bytes(batch: DataBatch) -> int:
        if isinstance(batch.payload, bytes):
            actual = len(batch.payload)
            return max(actual, batch.byte_count or 0)
        try:
            actual = len(
                json.dumps(
                    batch.payload,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            )
            return max(actual, batch.byte_count or 0)
        except (TypeError, ValueError) as exc:
            raise ConnectorResultViolation("connector payload is not finite JSON") from exc

    @staticmethod
    def _batch_rows(batch: DataBatch) -> int:
        if isinstance(batch.payload, (list, tuple)):
            actual = len(batch.payload)
            if batch.row_count is not None and batch.row_count != actual:
                raise ConnectorResultViolation("connector row count does not match its payload")
            return actual
        return batch.row_count or 0

    async def _authorize(
        self,
        identity: RequestIdentity,
        source_id: str,
        capability: Capability,
        asset_ids: tuple[str, ...],
        purpose: str,
        attributes: Mapping[str, Scalar],
        parameters: Mapping[str, object],
    ) -> None:
        decision = await self.policy.evaluate(
            AuthorizationRequest(
                identity,
                source_id,
                capability,
                asset_ids,
                purpose,
                attributes,
                parameters,
            )
        )
        await self.telemetry.emit(
            TelemetryEvent(
                "data.harness.authorization.decided",
                identity,
                attributes={
                    "source_id": source_id,
                    "capability": capability.value,
                    "allowed": decision.allowed,
                    "decision_id": decision.decision_id,
                    "reason_code": decision.reason_code,
                },
            )
        )
        if not decision.allowed:
            raise PolicyDenied(decision)
