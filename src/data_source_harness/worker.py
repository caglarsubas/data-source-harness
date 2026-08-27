"""Isolated connector-worker process boundary with bounded JSON-line RPC."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import signal
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_ENVIRONMENT = frozenset({"LANG", "LC_ALL"})
_SENSITIVE_NAME = re.compile(r"(?i)(credential|password|secret|token|api.?key|private.?key)")
_OPERATION = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")


class WorkerError(RuntimeError):
    pass


class WorkerTimeout(WorkerError):
    pass


class WorkerCrashed(WorkerError):
    pass


class WorkerProtocolViolation(WorkerError):
    pass


class WorkerRemoteError(WorkerError):
    pass


@dataclass(frozen=True)
class WorkerLimits:
    operation_timeout_seconds: float = 5.0
    max_request_bytes: int = 256 * 1024
    max_response_bytes: int = 1024 * 1024
    max_parallelism: int = 2

    def __post_init__(self) -> None:
        if (
            self.operation_timeout_seconds <= 0
            or self.max_request_bytes <= 0
            or self.max_response_bytes <= 0
            or self.max_parallelism <= 0
        ):
            raise ValueError("worker limits must be positive")


@dataclass(frozen=True)
class ConnectorWorkerSpec:
    worker_id: str
    connector_id: str
    command: tuple[str, ...]
    working_directory: Path
    credential_references: tuple[str, ...] = ()
    environment: Mapping[str, str] = field(default_factory=dict)
    limits: WorkerLimits = field(default_factory=WorkerLimits)
    image_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.worker_id or not self.connector_id or not self.command:
            raise ValueError("worker identity, connector identity and command are required")
        if not self.working_directory.is_absolute() or not self.working_directory.is_dir():
            raise ValueError("worker directory must be an existing absolute directory")
        executable = Path(self.command[0])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("worker executable must be an existing absolute file")
        if set(self.environment) - _SAFE_ENVIRONMENT or any(
            _SENSITIVE_NAME.search(name) for name in self.environment
        ):
            raise ValueError("worker environment is limited to non-sensitive process settings")
        if any(not name or not value for name, value in self.environment.items()):
            raise ValueError("worker environment names and values must be non-empty")
        if len(self.credential_references) != len(set(self.credential_references)):
            raise ValueError("credential references must be unique")
        if self.image_digest is not None and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.image_digest
        ):
            raise ValueError("worker image must be pinned by SHA-256 digest")
        if self.image_digest is not None:
            raise ValueError(
                "process worker specs cannot claim a container image; use a verified "
                "container runner"
            )

    @property
    def entrypoint_digest(self) -> str:
        materials = []
        for token in self.command:
            candidate = Path(token)
            if candidate.is_absolute() and candidate.is_file():
                materials.append(
                    {"path": token, "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest()}
                )
            else:
                materials.append({"argument": token})
        encoded = json.dumps(materials, sort_keys=True, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "workerId": self.worker_id,
            "connectorId": self.connector_id,
            "runtimeMode": "process",
            "imageDigest": None,
            "entrypointDigest": self.entrypoint_digest,
            "credentialReferences": list(self.credential_references),
            "limits": {
                "operationTimeoutMs": int(self.limits.operation_timeout_seconds * 1000),
                "maxRequestBytes": self.limits.max_request_bytes,
                "maxResponseBytes": self.limits.max_response_bytes,
                "maxParallelism": self.limits.max_parallelism,
            },
            "networkMode": "host",
            "certificationStatus": "process-isolation-only",
        }


class ConnectorWorkerClient:
    """Starts one replaceable subprocess per call; never invokes a shell."""

    def __init__(self, spec: ConnectorWorkerSpec) -> None:
        self.spec = spec
        self._semaphore = asyncio.Semaphore(spec.limits.max_parallelism)
        self._active = 0
        self.max_observed_parallelism = 0

    async def invoke(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        request_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        if not _OPERATION.fullmatch(operation):
            raise ValueError("worker operation name is invalid")
        request = {
            "protocol": "harness.worker/v1",
            "requestId": request_id or str(uuid4()),
            "operation": operation,
            "payload": dict(payload),
            "credentialReferences": list(self.spec.credential_references),
        }
        try:
            encoded = json.dumps(
                request,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as exc:
            raise ValueError("worker payload must be finite JSON") from exc
        if len(encoded) > self.spec.limits.max_request_bytes:
            raise WorkerProtocolViolation("worker request exceeds configured byte limit")
        async with self._semaphore:
            self._active += 1
            self.max_observed_parallelism = max(self.max_observed_parallelism, self._active)
            try:
                return await self._invoke(
                    encoded + b"\n", request["requestId"], timeout_seconds=timeout_seconds
                )
            finally:
                self._active -= 1

    async def _invoke(
        self, encoded: bytes, request_id: str, *, timeout_seconds: float | None
    ) -> Mapping[str, Any]:
        environment = {
            name: os.environ[name]
            for name in _SAFE_ENVIRONMENT
            if name in os.environ and not _SENSITIVE_NAME.search(name)
        }
        environment.update(self.spec.environment)
        process = await asyncio.create_subprocess_exec(
            *self.spec.command,
            cwd=self.spec.working_directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        timeout = self.spec.limits.operation_timeout_seconds
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                await self._terminate(process)
                raise WorkerTimeout("connector worker deadline is already exhausted")
            timeout = min(timeout, timeout_seconds)
        try:
            stdout, _stderr = await asyncio.wait_for(self._exchange(process, encoded), timeout)
        except TimeoutError as exc:
            await self._terminate(process)
            raise WorkerTimeout("connector worker exceeded its operation deadline") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        except WorkerProtocolViolation:
            await self._terminate(process)
            raise
        if process.returncode != 0:
            raise WorkerCrashed(f"connector worker exited with code {process.returncode}")
        if stdout.count(b"\n") != 1 or not stdout.endswith(b"\n"):
            raise WorkerProtocolViolation("worker must emit exactly one JSON line")
        try:
            response = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise WorkerProtocolViolation("worker response is not JSON") from exc
        if (
            not isinstance(response, dict)
            or response.get("protocol") != "harness.worker/v1"
            or response.get("requestId") != request_id
            or set(response) != {"protocol", "requestId", "result", "error"}
        ):
            raise WorkerProtocolViolation("worker response envelope is invalid")
        if response["error"] is not None:
            error = response["error"]
            code = error.get("code") if isinstance(error, dict) else "worker_error"
            raise WorkerRemoteError(str(code))
        if not isinstance(response["result"], dict):
            raise WorkerProtocolViolation("worker result must be an object")
        return response["result"]

    async def _exchange(
        self, process: asyncio.subprocess.Process, encoded: bytes
    ) -> tuple[bytes, bytes]:
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise WorkerProtocolViolation("worker pipes are unavailable")
        process.stdin.write(encoded)
        await process.stdin.drain()
        process.stdin.close()
        stdout_task = asyncio.create_task(
            self._read_bounded(
                process.stdout,
                self.spec.limits.max_response_bytes,
                "worker response exceeds configured byte limit",
            )
        )
        stderr_task = asyncio.create_task(
            self._read_bounded(
                process.stderr,
                min(self.spec.limits.max_response_bytes, 64 * 1024),
                "worker stderr exceeds configured byte limit",
            )
        )
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        await process.wait()
        return stdout, stderr

    @staticmethod
    async def _read_bounded(stream: asyncio.StreamReader, limit: int, message: str) -> bytes:
        chunks: list[bytes] = []
        size = 0
        while chunk := await stream.read(min(64 * 1024, limit - size + 1)):
            size += len(chunk)
            if size > limit:
                raise WorkerProtocolViolation(message)
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
