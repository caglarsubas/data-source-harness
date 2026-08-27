"""Version-pinned MCP and A2A profile adapters around the connector-neutral core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .delegation import A2AActionDelegationAdapter, DelegationRejected
from .policy import RequestIdentity
from .protocol import (
    PROTOCOL_VERSION,
    NorthboundActionAdapter,
    ProtocolRequestRejected,
)

MCP_PROTOCOL_VERSION = "2026-07-28"
A2A_PROTOCOL_VERSION = "1.0"
_MCP_META_VERSION = "io.modelcontextprotocol/protocolVersion"
_MCP_META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
_MCP_META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
_HARNESS_CATALOG_DIGEST = "data.harness/catalogDigest"


class ProtocolProfileRejected(PermissionError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class HttpDispatchResult:
    status: int
    headers: Mapping[str, str]
    body: Mapping[str, Any]


class Mcp20260728ActionServer:
    """Stateless MCP 2026-07-28 tools profile; transport hosting remains external."""

    def __init__(self, adapter: NorthboundActionAdapter, *, ttl_ms: int = 300_000) -> None:
        if ttl_ms <= 0:
            raise ValueError("MCP list TTL must be positive")
        self.adapter = adapter
        self.ttl_ms = ttl_ms

    def handle(self, request: Mapping[str, Any], identity: RequestIdentity) -> dict[str, Any]:
        request_id = request.get("id")
        try:
            self._validate_request(request)
            method = request["method"]
            if method == "tools/list":
                result = self._list_tools(request_id, identity)
            elif method == "tools/call":
                result = self._call_tool(request, identity)
            else:
                raise ProtocolProfileRejected(-32601, "MCP method is not exposed")
        except (ProtocolProfileRejected, ProtocolRequestRejected) as exc:
            code = exc.code
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": str(exc)},
            }
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def dispatch_http(
        self,
        headers: Mapping[str, str],
        request: Mapping[str, Any],
        identity: RequestIdentity,
    ) -> HttpDispatchResult:
        normalized = {name.lower(): value for name, value in headers.items()}
        try:
            if normalized.get("content-type", "").split(";", 1)[0] != "application/json":
                raise ProtocolProfileRejected(-32600, "MCP content type is invalid")
            method = request.get("method")
            if normalized.get("mcp-method") != method:
                raise ProtocolProfileRejected(-32600, "MCP method header mismatches body")
            if method == "tools/call":
                params = request.get("params")
                name = params.get("name") if isinstance(params, Mapping) else None
                if normalized.get("mcp-name") != name:
                    raise ProtocolProfileRejected(-32600, "MCP name header mismatches body")
            body = self.handle(request, identity)
            status = 200
        except ProtocolProfileRejected as exc:
            body = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": exc.code, "message": str(exc)},
            }
            status = 400
        return HttpDispatchResult(
            status,
            {"content-type": "application/json", "cache-control": "no-store"},
            body,
        )

    def _list_tools(self, request_id: str | int, identity: RequestIdentity) -> dict[str, Any]:
        internal = self.adapter.handle(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/list",
                "protocolVersion": PROTOCOL_VERSION,
            },
            identity,
        )
        tools = []
        for item in internal["result"]["tools"]:
            risk = item["risk"]
            tools.append(
                {
                    "name": item["name"],
                    "title": item["operation"],
                    "description": item["description"],
                    "inputSchema": item["inputSchema"],
                    "annotations": {
                        "readOnlyHint": False,
                        "destructiveHint": risk in {"medium", "high"},
                        "idempotentHint": True,
                        "openWorldHint": False,
                    },
                }
            )
        return {
            "resultType": "complete",
            "tools": tools,
            "ttlMs": self.ttl_ms,
            "cacheScope": "private",
            "_meta": {_HARNESS_CATALOG_DIGEST: self.adapter.catalog.digest},
        }

    def _call_tool(self, request: Mapping[str, Any], identity: RequestIdentity) -> dict[str, Any]:
        meta = request["_meta"]
        digest = meta.get(_HARNESS_CATALOG_DIGEST)
        params = request.get("params")
        if not isinstance(params, Mapping) or set(params) != {"name", "arguments"}:
            raise ProtocolProfileRejected(-32602, "MCP tool call parameters are invalid")
        internal = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "method": "tools/call",
            "protocolVersion": PROTOCOL_VERSION,
            "catalogDigest": digest,
            "params": dict(params),
        }
        action = self.adapter.to_action_plan(internal, identity)
        return {
            "resultType": "complete",
            "content": [
                {
                    "type": "text",
                    "text": "Governed action plan created; preview and approval remain required.",
                }
            ],
            "structuredContent": {
                "actionDigest": action.digest,
                "sourceAction": action.to_contract(),
                "executionRequired": True,
            },
            "isError": False,
        }

    @staticmethod
    def _validate_request(request: Mapping[str, Any]) -> None:
        allowed = {"jsonrpc", "id", "method", "params", "_meta"}
        if set(request) - allowed or request.get("jsonrpc") != "2.0":
            raise ProtocolProfileRejected(-32600, "MCP request envelope is invalid")
        if type(request.get("id")) not in {str, int}:
            raise ProtocolProfileRejected(-32600, "MCP request id is required")
        meta = request.get("_meta")
        if not isinstance(meta, Mapping):
            raise ProtocolProfileRejected(-32600, "MCP per-request metadata is required")
        required = {_MCP_META_VERSION, _MCP_META_CLIENT_INFO, _MCP_META_CAPABILITIES}
        if not required.issubset(meta) or meta[_MCP_META_VERSION] != MCP_PROTOCOL_VERSION:
            raise ProtocolProfileRejected(-32009, "MCP protocol version is unsupported")
        if not isinstance(meta[_MCP_META_CLIENT_INFO], Mapping) or not isinstance(
            meta[_MCP_META_CAPABILITIES], Mapping
        ):
            raise ProtocolProfileRejected(-32600, "MCP client metadata is invalid")


@dataclass(frozen=True)
class A2AAgentSkill:
    skill_id: str
    name: str
    description: str
    tags: tuple[str, ...]

    def to_contract(self) -> dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "inputModes": ["application/json"],
            "outputModes": ["application/json"],
        }


@dataclass(frozen=True)
class A2AAgentCard:
    name: str
    description: str
    url: str
    version: str
    skills: tuple[A2AAgentSkill, ...]

    def __post_init__(self) -> None:
        if not all((self.name, self.description, self.url, self.version)) or not self.skills:
            raise ValueError("A2A Agent Card identity and skills are required")

    def to_contract(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "supportedInterfaces": [
                {
                    "url": self.url,
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": A2A_PROTOCOL_VERSION,
                }
            ],
            "version": self.version,
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [skill.to_contract() for skill in self.skills],
        }


class A2A10ActionServer:
    """Bounded A2A 1.0 JSON-RPC SendMessage profile for action delegation."""

    def __init__(self, adapter: A2AActionDelegationAdapter, card: A2AAgentCard) -> None:
        self.adapter = adapter
        self.card = card

    def handle(
        self,
        headers: Mapping[str, str],
        request: Mapping[str, Any],
        identity: RequestIdentity,
    ) -> dict[str, Any]:
        request_id = request.get("id")
        normalized_headers = {name.lower(): value for name, value in headers.items()}
        try:
            if normalized_headers.get("a2a-version") != A2A_PROTOCOL_VERSION:
                raise ProtocolProfileRejected(-32009, "A2A protocol version is unsupported")
            if (
                set(request) != {"jsonrpc", "id", "method", "params"}
                or request.get("jsonrpc") != "2.0"
                or request.get("method") != "SendMessage"
                or type(request_id) not in {str, int}
            ):
                raise ProtocolProfileRejected(-32600, "A2A request envelope is invalid")
            params = request["params"]
            if not isinstance(params, Mapping) or set(params) != {"message"}:
                raise ProtocolProfileRejected(-32602, "A2A SendMessage params are invalid")
            message = params["message"]
            if (
                not isinstance(message, Mapping)
                or set(message) != {"messageId", "role", "parts"}
                or message.get("role") != "ROLE_USER"
                or not isinstance(message.get("messageId"), str)
            ):
                raise ProtocolProfileRejected(-32602, "A2A message is invalid")
            parts = message["parts"]
            if not isinstance(parts, list) or len(parts) != 1:
                raise ProtocolProfileRejected(-32602, "A2A action requires one data part")
            part = parts[0]
            if (
                not isinstance(part, Mapping)
                or set(part) != {"data", "mediaType"}
                or part.get("mediaType") != "application/json"
                or not isinstance(part.get("data"), Mapping)
            ):
                raise ProtocolProfileRejected(-32602, "A2A data part is invalid")
            action = self.adapter.to_action_plan(part["data"], identity)
        except (ProtocolProfileRejected, DelegationRejected) as exc:
            code = exc.code if isinstance(exc, ProtocolProfileRejected) else -32602
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": code, "message": str(exc)},
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "message": {
                    "messageId": f"response:{message['messageId']}",
                    "role": "ROLE_AGENT",
                    "parts": [
                        {
                            "data": {
                                "actionDigest": action.digest,
                                "sourceAction": action.to_contract(),
                                "executionRequired": True,
                            },
                            "mediaType": "application/json",
                        }
                    ],
                }
            },
        }
