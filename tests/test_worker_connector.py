from types import SimpleNamespace

import pytest

from data_source_harness.connector import (
    Capability,
    ConnectorProfile,
    DataModel,
    RuntimeMode,
    UnsupportedCapability,
)
from data_source_harness.deployment import (
    DeploymentMode,
    DeploymentProfile,
    EgressDenied,
    EgressGuard,
)
from data_source_harness.models import AssetRef, QueryRequest, SearchRequest
from data_source_harness.worker_connector import WorkerBackedConnector

NOW = "2026-08-27T00:00:00+00:00"


def version() -> dict[str, object]:
    return {
        "sourceId": "lab.worker",
        "version": "v1",
        "observedAt": NOW,
        "effectiveAt": None,
    }


def lineage() -> dict[str, object]:
    return {
        "sourceId": "lab.worker",
        "assetId": "orders",
        "recordId": "order-1",
        "fieldPath": None,
    }


class FakeClient:
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.spec = SimpleNamespace(connector_id="lab.worker")
        self.responses = responses or {}
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def invoke(self, operation, payload, **kwargs):
        self.calls.append((operation, dict(payload)))
        if operation in self.responses:
            return self.responses[operation]
        defaults = {
            "connector.health": {
                "healthy": True,
                "observedVersion": "v1",
                "limitations": ["fixture"],
            },
            "connector.discover": {
                "assets": [
                    {
                        "assetId": "orders",
                        "name": "Orders",
                        "kind": "table",
                        "description": None,
                        "metadata": {"tier": "lab"},
                    }
                ]
            },
            "connector.describe": {
                "fields": [
                    {
                        "name": "order_id",
                        "logicalType": "string",
                        "nullable": False,
                        "description": None,
                        "metadata": {},
                    }
                ],
                "version": version(),
            },
            "connector.query": {
                "batches": [
                    {
                        "kind": "arrow",
                        "payload": [{"order_id": "order-1"}],
                        "sourceVersions": [version()],
                        "lineage": [lineage()],
                        "rowCount": 1,
                        "byteCount": 24,
                    }
                ]
            },
            "connector.search": {
                "hits": [
                    {
                        "sourceId": "lab.worker",
                        "assetId": "orders-index",
                        "recordId": "order-1",
                        "fusionScore": 0.9,
                        "lexicalScore": 0.8,
                        "denseScore": None,
                        "sparseScore": None,
                        "rerankerScore": 0.7,
                        "sourceVersion": version(),
                        "lineage": [lineage()],
                        "aclDecisionId": "acl:1",
                    }
                ]
            },
            "connector.mutate": {"accepted": True},
            "connector.checkpoint": {"checkpoint": "42"},
            "connector.explain": {"bounded": True},
        }
        return defaults[operation]


def profile() -> ConnectorProfile:
    return ConnectorProfile(
        "lab.worker",
        "1.0.0",
        "harness.connector/v1",
        RuntimeMode.PROCESS,
        frozenset({DataModel.TABULAR}),
        frozenset(
            {
                Capability.DISCOVER,
                Capability.DESCRIBE,
                Capability.QUERY,
                Capability.SEARCH,
                Capability.MUTATE,
                Capability.EXPLAIN,
            }
        ),
        frozenset({"credential_reference"}),
    )


async def test_worker_connector_translates_every_supported_shape() -> None:
    client = FakeClient()
    connector = WorkerBackedConnector(profile(), client)  # type: ignore[arg-type]
    assert (await connector.health()).limitations == ("fixture",)
    assert (await connector.discover())[0].ref == AssetRef("lab.worker", "orders")
    assert (await connector.describe(AssetRef("lab.worker", "orders"))).fields[0].name == "order_id"
    batches = [
        batch
        async for batch in connector.execute(
            QueryRequest("lab.worker", ("orders",), {}, 10, 1_000, "test")
        )
    ]
    assert batches[0].payload == [{"order_id": "order-1"}]
    hits = await connector.search(SearchRequest("lab.worker", "order", 1))
    assert hits[0].reranker_score == 0.7 and hits[0].acl_decision_id == "acl:1"
    assert await connector.mutate({"action": "test"}) == {"accepted": True}
    assert await connector.checkpoint("events") == "42"
    assert (
        await connector.explain(QueryRequest("lab.worker", ("orders",), {}, 10, 1_000, "test"))
    ) == {"bounded": True}
    with pytest.raises(UnsupportedCapability):
        _ = [item async for item in connector.subscribe()]


async def test_worker_connector_rejects_identity_and_malformed_results() -> None:
    with pytest.raises(ValueError, match="identities"):
        WorkerBackedConnector(
            profile(),
            SimpleNamespace(spec=SimpleNamespace(connector_id="other")),  # type: ignore[arg-type]
        )
    connector = WorkerBackedConnector(profile(), FakeClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="asset source"):
        await connector.describe(AssetRef("other", "orders"))
    with pytest.raises(ValueError, match="query source"):
        _ = [
            item
            async for item in connector.execute(
                QueryRequest("other", ("orders",), {}, 10, 1_000, "test")
            )
        ]
    with pytest.raises(ValueError, match="search source"):
        await connector.search(SearchRequest("other", "order", 1))

    cases = (
        ("connector.discover", {"assets": ["bad"]}),
        (
            "connector.describe",
            {"fields": ["bad"], "version": version()},
        ),
        (
            "connector.search",
            {"hits": ["bad"]},
        ),
    )
    for operation, response in cases:
        subject = WorkerBackedConnector(  # type: ignore[arg-type]
            profile(), FakeClient({operation: response})
        )
        with pytest.raises(ValueError, match="structured"):
            if operation == "connector.discover":
                await subject.discover()
            elif operation == "connector.describe":
                await subject.describe(AssetRef("lab.worker", "orders"))
            else:
                await subject.search(SearchRequest("lab.worker", "order", 1))


async def test_worker_connector_enforces_remote_egress_profile() -> None:
    airgap = DeploymentProfile(
        "airgap",
        DeploymentMode.AIR_GAPPED,
        frozenset({"worker.internal"}),
        False,
        False,
        True,
    )
    with pytest.raises(ValueError, match="both endpoint"):
        WorkerBackedConnector(profile(), FakeClient(), endpoint="https://worker.internal")  # type: ignore[arg-type]
    allowed = WorkerBackedConnector(  # type: ignore[arg-type]
        profile(),
        FakeClient(),
        endpoint="https://worker.internal",
        egress_guard=EgressGuard(airgap),
    )
    assert (await allowed.health()).healthy
    denied = WorkerBackedConnector(  # type: ignore[arg-type]
        profile(),
        FakeClient(),
        endpoint="https://public.example",
        egress_guard=EgressGuard(airgap),
    )
    with pytest.raises(EgressDenied):
        await denied.health()
