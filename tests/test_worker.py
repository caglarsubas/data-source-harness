from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    ConnectorRegistry,
    DataModel,
    RuntimeMode,
)
from data_source_harness.models import QueryRequest
from data_source_harness.policy import RequestIdentity, StaticPolicy
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink
from data_source_harness.worker import (
    ConnectorWorkerClient,
    ConnectorWorkerSpec,
    WorkerCrashed,
    WorkerLimits,
    WorkerProtocolViolation,
    WorkerTimeout,
)
from data_source_harness.worker_connector import WorkerBackedConnector

ROOT = Path(__file__).resolve().parents[1]


def spec(
    mode: str = "normal", *, timeout: float = 2.0, response_bytes: int = 1024 * 1024
) -> ConnectorWorkerSpec:
    return ConnectorWorkerSpec(
        f"whitegoods-{mode}",
        "whitegoods.reference-worker",
        (
            str(Path(sys.executable).resolve()),
            str(ROOT / "reference_labs/white_goods/phase6_worker.py"),
            "--mode",
            mode,
        ),
        ROOT,
        ("credential://whitegoods/reference",),
        limits=WorkerLimits(timeout, 256 * 1024, response_bytes, 2),
    )


async def test_worker_executes_four_source_shapes_without_inheriting_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-enter-worker")
    client = ConnectorWorkerClient(spec())
    postgres = await client.invoke("postgres.query", {}, request_id="postgres")
    object_store = await client.invoke(
        "s3.get", {"name": "washing-machine-e21-manual.md"}, request_id="s3"
    )
    events = await client.invoke("events.poll", {}, request_id="events")
    rest = await client.invoke("rest.get", {}, request_id="rest")
    environment = await client.invoke("runtime.environment", {}, request_id="environment")
    assert postgres["rows"] == 6
    assert object_store["bytes"] > 0 and len(object_store["sha256"]) == 64
    assert events["events"] > 0 and rest["records"] > 0
    assert environment["sensitiveVariablesPresent"] == []


async def test_worker_timeout_crash_response_limit_and_parallelism_fail_closed() -> None:
    with pytest.raises(WorkerTimeout):
        await ConnectorWorkerClient(spec("slow", timeout=0.05)).invoke("rest.get", {})
    with pytest.raises(WorkerCrashed):
        await ConnectorWorkerClient(spec("crash")).invoke("rest.get", {})
    with pytest.raises(WorkerProtocolViolation):
        await ConnectorWorkerClient(spec("oversize", response_bytes=512)).invoke("rest.get", {})
    client = ConnectorWorkerClient(spec("slow"))
    await asyncio.gather(*(client.invoke("rest.get", {}) for _ in range(4)))
    assert client.max_observed_parallelism == 2


async def test_cancelled_worker_is_terminated() -> None:
    task = asyncio.create_task(ConnectorWorkerClient(spec("slow")).invoke("rest.get", {}))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_worker_rejects_non_finite_json_before_process_start() -> None:
    with pytest.raises(ValueError, match="finite JSON"):
        await ConnectorWorkerClient(spec()).invoke("rest.get", {"value": float("nan")})


def test_process_worker_cannot_self_attest_as_an_image_pinned_container() -> None:
    with pytest.raises(ValueError, match="cannot claim a container image"):
        ConnectorWorkerSpec(
            "spoofed",
            "whitegoods.reference-worker",
            (str(Path(sys.executable).resolve()), "-c", "print('not a container')"),
            ROOT,
            image_digest="sha256:" + "a" * 64,
        )


async def test_gateway_executes_canonical_query_through_worker_boundary() -> None:
    profile = ConnectorProfile(
        "whitegoods.reference-worker",
        "0.11.0",
        "harness.connector/v1",
        RuntimeMode.PROCESS,
        frozenset({DataModel.TABULAR}),
        frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
        frozenset({"credential_reference"}),
        limits=ConnectorLimits(max_parallelism=2, max_result_bytes=128 * 1024),
    )
    connector = WorkerBackedConnector(profile, ConnectorWorkerClient(spec()))
    registry = ConnectorRegistry()
    registry.register(connector)
    gateway = HarnessGateway(
        registry,
        StaticPolicy({("whitegoods.reference-worker", Capability.QUERY)}),
        MemoryTelemetrySink(),
    )
    request = QueryRequest(
        "whitegoods.reference-worker",
        ("service_orders",),
        {
            "select_by_asset": {"service_orders": ["service_order_id", "error_code"]},
            "where_by_asset": {"service_orders": {"error_code": "E21"}},
            "relationships": [],
        },
        20,
        1_000,
        "phase6.5 worker integration",
    )
    identity = RequestIdentity(
        "org-lab", "whitegoods", "agent-quality", "worker-query", "trace", "policy:v1"
    )
    batches = [batch async for batch in gateway.execute(request, identity)]
    assert batches[0].row_count == 2
    assert {row["error_code"] for row in batches[0].payload} == {"E21"}
    assert connector.client.max_observed_parallelism == 1
