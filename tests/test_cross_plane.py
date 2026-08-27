from datetime import UTC, datetime

import pytest

from data_source_harness.connector import Capability, ConnectorRegistry
from data_source_harness.coordination import CrossSourceCoordinator, QueryStep, SourceExecutionPlan
from data_source_harness.cross_plane import CrossPlaneEvidenceBridge, GovernedModelPlane
from data_source_harness.models import QueryRequest
from data_source_harness.policy import RequestIdentity, StaticPolicy
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink

from .helpers import FakeConnector


class EvidenceSink:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.received = []

    async def publish_execution_evidence(self, evidence):
        self.received.append(dict(evidence))
        return f"{self.prefix}:receipt"

    async def ingest_runtime_evidence(self, evidence):
        self.received.append(dict(evidence))
        return f"{self.prefix}:evidence"


class ModelClient:
    def __init__(self, scores):
        self.scores = scores
        self.tenant = None

    async def rerank(self, *, request_id, query, candidates, tenant):
        self.tenant = dict(tenant)
        return self.scores


def identity() -> RequestIdentity:
    return RequestIdentity("org", "solution", "agent", "cross-1", "trace", "policy:v1")


async def coordinated_result():
    registry = ConnectorRegistry()
    registry.register(FakeConnector("erp"))
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("erp", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    return await CrossSourceCoordinator(gateway).execute(
        SourceExecutionPlan(
            "cross-1",
            datetime(2026, 8, 27, tzinfo=UTC),
            (
                QueryStep(
                    "erp",
                    QueryRequest("erp", ("orders",), {}, 10, 1_000, "cross-plane"),
                ),
            ),
        ),
        identity(),
    )


async def test_cross_plane_bridge_binds_sdk_receipt_into_adlc_evidence() -> None:
    sdk = EvidenceSink("sdk")
    adlc = EvidenceSink("adlc")
    receipt = await CrossPlaneEvidenceBridge(sdk, adlc).publish(
        await coordinated_result(), identity()
    )
    assert receipt.sdk_receipt_id == "sdk:receipt"
    assert receipt.adlc_evidence_id == "adlc:evidence"
    assert adlc.received[0]["sdkReceiptId"] == receipt.sdk_receipt_id
    assert "lineageDigest" in sdk.received[0]
    assert "payload" not in sdk.received[0]


async def test_model_plane_scores_are_tenant_bound_bounded_and_validated() -> None:
    client = ModelClient((0.2, 0.9, 0.9))
    ranking = await GovernedModelPlane(client, max_candidates=3).rerank(
        "E21", ("a", "b", "c"), identity()
    )
    assert ranking == (1, 2, 0)
    assert client.tenant == {
        "organizationId": "org",
        "solutionId": "solution",
        "agentId": "agent",
    }
    with pytest.raises(ValueError, match="invalid rerank"):
        await GovernedModelPlane(ModelClient((float("nan"),))).rerank("E21", ("a",), identity())
