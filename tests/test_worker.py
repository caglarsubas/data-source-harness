from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from data_source_harness.worker import (
    ConnectorWorkerClient,
    ConnectorWorkerSpec,
    WorkerCrashed,
    WorkerLimits,
    WorkerProtocolViolation,
    WorkerTimeout,
)

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
