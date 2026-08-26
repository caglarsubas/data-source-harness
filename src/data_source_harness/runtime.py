"""Policy-enforcing gateway for connector execution."""

from __future__ import annotations

from collections.abc import AsyncIterator

from .connector import Capability, ConnectorRegistry
from .models import Asset, DataBatch, QueryRequest
from .policy import AuthorizationRequest, PolicyDenied, PolicyEvaluator, RequestIdentity
from .telemetry import TelemetryEvent, TelemetrySink


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

    async def discover(self, source_id: str, identity: RequestIdentity) -> tuple[Asset, ...]:
        connector = self.registry.get(source_id, Capability.DISCOVER)
        await self._authorize(identity, source_id, Capability.DISCOVER, (), "asset discovery")
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
        )
        async for batch in connector.execute(request):
            await self.telemetry.emit(
                TelemetryEvent(
                    "data.harness.batch.emitted",
                    identity,
                    attributes={
                        "source_id": request.source_id,
                        "kind": batch.kind.value,
                        "row_count": batch.row_count,
                    },
                )
            )
            yield batch

    async def _authorize(
        self,
        identity: RequestIdentity,
        source_id: str,
        capability: Capability,
        asset_ids: tuple[str, ...],
        purpose: str,
    ) -> None:
        decision = await self.policy.evaluate(
            AuthorizationRequest(identity, source_id, capability, asset_ids, purpose)
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
