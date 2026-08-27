"""Stateless JSON-RPC northbound action boundary with pinned tool metadata."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .actions import (
    ActionRisk,
    ApprovalMode,
    CompensationSpec,
    SourceActionPlan,
)
from .models import Scalar
from .policy import RequestIdentity

PROTOCOL_VERSION = "data.harness.northbound/v1"


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ProtocolRequestRejected(PermissionError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class NorthboundTool:
    name: str
    description: str
    source_id: str
    asset_id: str
    operation: str
    risk: ActionRisk
    approval_mode: ApprovalMode
    purpose: str
    allowed_agents: frozenset[str]

    def __post_init__(self) -> None:
        values = (
            self.name,
            self.description,
            self.source_id,
            self.asset_id,
            self.operation,
            self.purpose,
        )
        if any(not value for value in values) or not self.allowed_agents:
            raise ValueError("northbound tools require metadata and at least one allowed agent")

    def to_contract(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "sourceId": self.source_id,
            "assetId": self.asset_id,
            "operation": self.operation,
            "risk": self.risk.value,
            "approvalMode": self.approval_mode.value,
            "purpose": self.purpose,
            "allowedAgents": sorted(self.allowed_agents),
        }

    def exposed_contract(self) -> dict[str, Any]:
        contract = self.to_contract()
        contract.pop("allowedAgents")
        contract["inputSchema"] = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "actionId",
                "parameters",
                "preconditions",
                "idempotencyKey",
            ],
            "properties": {
                "actionId": {"type": "string"},
                "parameters": {"type": "object"},
                "preconditions": {"type": "object"},
                "idempotencyKey": {"type": "string"},
                "compensation": {"type": ["object", "null"]},
            },
        }
        return contract


@dataclass(frozen=True)
class NorthboundToolCatalog:
    tools: tuple[NorthboundTool, ...]

    def __post_init__(self) -> None:
        names = [tool.name for tool in self.tools]
        if not names or len(names) != len(set(names)):
            raise ValueError("tool catalog requires at least one uniquely named tool")

    @property
    def digest(self) -> str:
        contracts = [tool.to_contract() for tool in sorted(self.tools, key=lambda item: item.name)]
        return _digest(contracts)

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "protocolVersion": PROTOCOL_VERSION,
            "catalogDigest": self.digest,
            "tools": [
                tool.to_contract() for tool in sorted(self.tools, key=lambda item: item.name)
            ],
        }


class NorthboundActionAdapter:
    """Maps a small tools/list + tools/call surface to bounded source action plans."""

    _request_fields = frozenset(
        {"jsonrpc", "id", "method", "protocolVersion", "catalogDigest", "params"}
    )
    _argument_fields = frozenset(
        {"actionId", "parameters", "preconditions", "idempotencyKey", "compensation"}
    )

    def __init__(self, catalog: NorthboundToolCatalog) -> None:
        self.catalog = catalog
        self._tools = {tool.name: tool for tool in catalog.tools}

    def handle(self, request: Mapping[str, Any], identity: RequestIdentity) -> dict[str, Any]:
        request_id = request.get("id")
        try:
            self._validate_envelope(request)
            if request["method"] == "tools/list":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "catalogDigest": self.catalog.digest,
                    "tools": [
                        tool.exposed_contract()
                        for tool in sorted(self.catalog.tools, key=lambda item: item.name)
                        if identity.agent_id in tool.allowed_agents
                    ],
                }
            elif request["method"] == "tools/call":
                action = self.to_action_plan(request, identity)
                result = {
                    "actionDigest": action.digest,
                    "sourceAction": action.to_contract(),
                    "executionRequired": True,
                }
            else:
                raise ProtocolRequestRejected(-32601, "method is not exposed")
        except ProtocolRequestRejected as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": str(exc)},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def to_action_plan(
        self, request: Mapping[str, Any], identity: RequestIdentity
    ) -> SourceActionPlan:
        self._validate_envelope(request)
        if request["method"] != "tools/call":
            raise ProtocolRequestRejected(-32601, "request is not a tool call")
        if request.get("catalogDigest") != self.catalog.digest:
            raise ProtocolRequestRejected(-32010, "tool catalog digest is stale or mismatched")
        params = request.get("params")
        if not isinstance(params, Mapping) or set(params) != {"name", "arguments"}:
            raise ProtocolRequestRejected(-32602, "tool call params are not exact")
        name = params["name"]
        if not isinstance(name, str) or name not in self._tools:
            raise ProtocolRequestRejected(-32602, "tool is unknown")
        tool = self._tools[name]
        if identity.agent_id not in tool.allowed_agents:
            raise ProtocolRequestRejected(-32003, "tool is outside agent scope")
        arguments = params["arguments"]
        if not isinstance(arguments, Mapping):
            raise ProtocolRequestRejected(-32602, "tool arguments must be an object")
        unexpected = set(arguments) - self._argument_fields
        required = {"actionId", "parameters", "preconditions", "idempotencyKey"}
        if unexpected or not required.issubset(arguments):
            raise ProtocolRequestRejected(-32602, "tool arguments are over-broad or incomplete")
        parameters = self._scalar_mapping(arguments["parameters"], "parameters")
        preconditions = self._scalar_mapping(arguments["preconditions"], "preconditions")
        compensation = self._compensation(arguments.get("compensation"))
        try:
            return SourceActionPlan(
                str(arguments["actionId"]),
                tool.source_id,
                tool.asset_id,
                tool.operation,
                parameters,
                preconditions,
                str(arguments["idempotencyKey"]),
                tool.risk,
                tool.approval_mode,
                tool.purpose,
                compensation,
            )
        except (TypeError, ValueError) as exc:
            raise ProtocolRequestRejected(-32602, "tool arguments violate action contract") from exc

    @classmethod
    def _validate_envelope(cls, request: Mapping[str, Any]) -> None:
        if set(request) - cls._request_fields:
            raise ProtocolRequestRejected(-32600, "request envelope is over-broad")
        if request.get("jsonrpc") != "2.0" or request.get("protocolVersion") != PROTOCOL_VERSION:
            raise ProtocolRequestRejected(-32600, "protocol version is unsupported")
        if not isinstance(request.get("id"), str | int):
            raise ProtocolRequestRejected(-32600, "request id is required")

    @staticmethod
    def _scalar_mapping(value: object, name: str) -> Mapping[str, Scalar]:
        if not isinstance(value, Mapping) or not value:
            raise ProtocolRequestRejected(-32602, f"{name} must be a non-empty object")
        if any(
            not isinstance(key, str) or not isinstance(item, str | int | float | bool | type(None))
            for key, item in value.items()
        ):
            raise ProtocolRequestRejected(-32602, f"{name} values must be scalar")
        return dict(value)

    @classmethod
    def _compensation(cls, value: object) -> CompensationSpec | None:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {
            "operation",
            "parameters",
            "preconditions",
        }:
            raise ProtocolRequestRejected(-32602, "compensation is not exact")
        return CompensationSpec(
            str(value["operation"]),
            cls._scalar_mapping(value["parameters"], "compensation parameters"),
            cls._scalar_mapping(value["preconditions"], "compensation preconditions"),
        )
