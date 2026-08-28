from __future__ import annotations

from data_source_harness.delegation import A2AActionDelegationAdapter
from data_source_harness.policy import RequestIdentity
from data_source_harness.protocol import (
    NorthboundActionAdapter,
    NorthboundTool,
    NorthboundToolCatalog,
)
from data_source_harness.protocol_profiles import (
    A2A_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    A2A10ActionServer,
    A2AAgentCard,
    A2AAgentSkill,
    Mcp20260728ActionServer,
)
from reference_labs.white_goods.phase4 import service_action


def identity(agent: str = "agent.whitegoods-service") -> RequestIdentity:
    return RequestIdentity("org-lab", "whitegoods-lab", agent, "request", "trace", "policy:wg-v1")


def tool_catalog() -> NorthboundToolCatalog:
    action = service_action()
    return NorthboundToolCatalog(
        (
            NorthboundTool(
                "whitegoods.reschedule",
                "Reschedule one approved service appointment",
                action.source_id,
                action.asset_id,
                action.operation,
                action.risk,
                action.approval_mode,
                action.purpose,
                frozenset({"agent.whitegoods-service"}),
            ),
        )
    )


def meta(digest: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "phase6-test", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    if digest:
        value["data.harness/catalogDigest"] = digest
    return value


def mcp_call(digest: str) -> dict[str, object]:
    action = service_action()
    return {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "_meta": meta(digest),
        "params": {
            "name": "whitegoods.reschedule",
            "arguments": {
                "actionId": action.action_id,
                "parameters": dict(action.parameters),
                "preconditions": dict(action.preconditions),
                "idempotencyKey": action.idempotency_key,
                "compensation": {
                    "operation": action.compensation.operation,
                    "parameters": dict(action.compensation.parameters),
                    "preconditions": dict(action.compensation.preconditions),
                },
            },
        },
    }


def test_mcp_profile_is_stateless_scoped_pinned_and_header_bound() -> None:
    catalog = tool_catalog()
    server = Mcp20260728ActionServer(NorthboundActionAdapter(catalog))
    list_request = {
        "jsonrpc": "2.0",
        "id": "list-1",
        "method": "tools/list",
        "params": {},
        "_meta": meta(),
    }
    first = server.handle(list_request, identity())
    second = server.handle(list_request, identity())
    assert first == second
    assert first["result"]["resultType"] == "complete"
    assert first["result"]["cacheScope"] == "private"
    assert len(first["result"]["tools"]) == 1
    outsider = server.handle(list_request, identity("agent.outsider"))
    assert outsider["result"]["tools"] == []
    call = mcp_call(catalog.digest)
    response = server.dispatch_http(
        {
            "Content-Type": "application/json",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "whitegoods.reschedule",
        },
        call,
        identity(),
    )
    assert response.status == 200
    assert response.body["result"]["structuredContent"]["executionRequired"] is True
    mismatch = server.dispatch_http(
        {"Content-Type": "application/json", "Mcp-Method": "tools/list"},
        call,
        identity(),
    )
    assert mismatch.status == 400
    stale = server.handle(mcp_call("sha256:" + "0" * 64), identity())
    assert stale["error"]["code"] == -32010


def a2a_envelope() -> dict[str, object]:
    action = service_action()
    return {
        "protocol": "a2a/1.0",
        "taskId": "task-reschedule-1",
        "requestingAgent": "agent.whitegoods-service",
        "sourceAction": {
            "actionId": action.action_id,
            "sourceId": action.source_id,
            "assetId": action.asset_id,
            "operation": action.operation,
            "parameters": dict(action.parameters),
            "preconditions": dict(action.preconditions),
            "idempotencyKey": action.idempotency_key,
            "risk": action.risk.value,
            "approvalMode": action.approval_mode.value,
            "purpose": action.purpose,
            "compensation": {
                "operation": action.compensation.operation,
                "parameters": dict(action.compensation.parameters),
                "preconditions": dict(action.compensation.preconditions),
            },
        },
    }


def test_a2a_profile_advertises_v1_and_maps_one_data_part_without_execution() -> None:
    action = service_action()
    card = A2AAgentCard(
        "Harness actions",
        "Governed source action delegation",
        "https://harness.internal/a2a",
        "0.12.0",
        (A2AAgentSkill("source-action", "Source action", "Delegate a bounded action", ("data",)),),
    )
    assert card.to_contract()["supportedInterfaces"][0]["protocolVersion"] == A2A_PROTOCOL_VERSION
    server = A2A10ActionServer(
        A2AActionDelegationAdapter(frozenset({(action.source_id, action.operation)})), card
    )
    request = {
        "jsonrpc": "2.0",
        "id": "a2a-1",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "message-1",
                "role": "ROLE_USER",
                "parts": [{"data": a2a_envelope(), "mediaType": "application/json"}],
            }
        },
    }
    response = server.handle({"a2a-version": "1.0"}, request, identity())
    data = response["result"]["message"]["parts"][0]["data"]
    assert data["actionDigest"] == action.digest and data["executionRequired"] is True
    wrong_version = server.handle({"A2A-Version": "0.3"}, request, identity())
    assert wrong_version["error"]["code"] == -32009
    invalid_id = server.handle({"A2A-Version": "1.0"}, {**request, "id": True}, identity())
    assert invalid_id["error"]["code"] == -32600

    malformed = a2a_envelope()
    malformed["sourceAction"]["compensation"] = {}
    malformed_request = {
        **request,
        "params": {
            "message": {
                "messageId": "message-bad",
                "role": "ROLE_USER",
                "parts": [{"data": malformed, "mediaType": "application/json"}],
            }
        },
    }
    rejected = server.handle({"A2A-Version": "1.0"}, malformed_request, identity())
    assert rejected["error"]["code"] == -32602
