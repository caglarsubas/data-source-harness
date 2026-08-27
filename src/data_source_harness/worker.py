"""Isolated connector-worker process boundary with bounded JSON-line RPC."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

_SAFE_ENVIRONMENT = frozenset({"LANG", "LC_ALL", "PATH", "PYTHONPATH"})
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

    @property
    def entrypoint_digest(self) -> str:
        encoded = json.dumps(self.command, separators=(",", ":")).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "workerId": self.worker_id,
            "connectorId": self.connector_id,
            "runtimeMode": "container" if self.image_digest else "process",
            "imageDigest": self.image_digest,
            "entrypointDigest": self.entrypoint_digest,
            "credentialReferences": list(self.credential_references),
            "limits": {
                "operationTimeoutMs": int(self.limits.operation_timeout_seconds * 1000),
                "maxRequestBytes": self.limits.max_request_bytes,
                "maxResponseBytes": self.limits.max_response_bytes,
                "maxParallelism": self.limits.max_parallelism,
            },
            "networkMode": "none" if self.image_digest else "host",
            "certificationStatus": (
                "image-pinned" if self.image_digest else "process-isolation-only"
            ),
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
                return await self._invoke(encoded + b"\n", request["requestId"])
            finally:
                self._active -= 1

    async def _invoke(self, encoded: bytes, request_id: str) -> Mapping[str, Any]:
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
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(encoded), self.spec.limits.operation_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise WorkerTimeout("connector worker exceeded its operation deadline") from exc
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise WorkerCrashed(f"connector worker exited with code {process.returncode}")
        if len(stdout) > self.spec.limits.max_response_bytes:
            raise WorkerProtocolViolation("worker response exceeds configured byte limit")
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
