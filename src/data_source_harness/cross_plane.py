"""Executable, tenant-neutral seams to the surrounding ADLC platform planes."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .coordination import CoordinationResult
from .policy import RequestIdentity


def _digest(value: object) -> str:
    encoded = json.dumps(value, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class SDKExecutionEvidenceSink(Protocol):
    async def publish_execution_evidence(self, evidence: Mapping[str, Any]) -> str: ...


class ADLCEvidenceSink(Protocol):
    async def ingest_runtime_evidence(self, evidence: Mapping[str, Any]) -> str: ...


class ModelPlaneClient(Protocol):
    async def rerank(
        self,
        *,
        request_id: str,
        query: str,
        candidates: Sequence[str],
        tenant: Mapping[str, str],
    ) -> Sequence[float]: ...


@dataclass(frozen=True)
class CrossPlaneReceipt:
    request_id: str
    evidence_digest: str
    sdk_receipt_id: str
    adlc_evidence_id: str


class CrossPlaneEvidenceBridge:
    """Publish one redacted execution claim to SDK and ADLC evidence owners."""

    def __init__(
        self,
        sdk_sink: SDKExecutionEvidenceSink,
        adlc_sink: ADLCEvidenceSink,
    ) -> None:
        self.sdk_sink = sdk_sink
        self.adlc_sink = adlc_sink

    async def publish(
        self, result: CoordinationResult, identity: RequestIdentity
    ) -> CrossPlaneReceipt:
        if result.request_id != identity.request_id:
            raise ValueError("coordination result and tenant request identity must match")
        evidence = self._evidence(result, identity)
        evidence_digest = _digest(evidence)
        sdk_receipt = await self.sdk_sink.publish_execution_evidence(
            {**evidence, "evidenceDigest": evidence_digest}
        )
        if not sdk_receipt:
            raise ValueError("Python-SDK evidence sink returned no receipt identity")
        adlc_evidence = await self.adlc_sink.ingest_runtime_evidence(
            {
                **evidence,
                "evidenceDigest": evidence_digest,
                "sdkReceiptId": sdk_receipt,
            }
        )
        if not adlc_evidence:
            raise ValueError("ADLC evidence sink returned no evidence identity")
        return CrossPlaneReceipt(
            result.request_id,
            evidence_digest,
            sdk_receipt,
            adlc_evidence,
        )

    @staticmethod
    def _evidence(result: CoordinationResult, identity: RequestIdentity) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness.cross-plane-execution/v1",
            "organizationId": identity.organization_id,
            "solutionId": identity.solution_id,
            "agentId": identity.agent_id,
            "requestId": identity.request_id,
            "traceId": identity.trace_id,
            "policyDigest": identity.policy_digest,
            "complete": result.complete,
            "includedSources": sorted(item.source_id for item in result.coverage.included),
            "excludedSources": sorted(item.source_id for item in result.coverage.excluded),
            "lineageDigest": _digest(
                [
                    {
                        "sourceId": item.source_id,
                        "assetId": item.asset_id,
                        "recordId": item.record_id,
                        "fieldPath": item.field_path,
                    }
                    for item in result.lineage
                ]
            ),
        }


class GovernedModelPlane:
    """Validate local model-plane reranking without coupling its SDK into core."""

    def __init__(self, client: ModelPlaneClient, *, max_candidates: int = 100) -> None:
        if max_candidates <= 0:
            raise ValueError("model-plane candidate bound must be positive")
        self.client = client
        self.max_candidates = max_candidates

    async def rerank(
        self,
        query: str,
        candidates: Sequence[str],
        identity: RequestIdentity,
    ) -> tuple[int, ...]:
        if not query.strip() or not candidates or len(candidates) > self.max_candidates:
            raise ValueError("rerank requires a query and bounded candidates")
        scores = tuple(
            await self.client.rerank(
                request_id=identity.request_id,
                query=query,
                candidates=tuple(candidates),
                tenant={
                    "organizationId": identity.organization_id,
                    "solutionId": identity.solution_id,
                    "agentId": identity.agent_id,
                },
            )
        )
        if len(scores) != len(candidates) or any(
            not isinstance(score, (int, float)) or not math.isfinite(score) for score in scores
        ):
            raise ValueError("model-plane returned invalid rerank scores")
        return tuple(sorted(range(len(scores)), key=lambda index: (-scores[index], index)))
