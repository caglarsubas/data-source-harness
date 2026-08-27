from __future__ import annotations

from dataclasses import replace

from data_source_harness.actions import ActionRisk, ApprovalMode
from data_source_harness.policy import RequestIdentity
from data_source_harness.protocol import (
    PROTOCOL_VERSION,
    NorthboundActionAdapter,
    NorthboundTool,
    NorthboundToolCatalog,
)


def identity(agent: str = "agent.worker") -> RequestIdentity:
    return RequestIdentity("org", "solution", agent, "request", "trace", "policy:v1")


def tool() -> NorthboundTool:
    return NorthboundTool(
        "cases.close",
        "Close an approved case",
        "case.actions",
        "cases",
        "close-case",
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "close a verified case",
        frozenset({"agent.worker"}),
    )


def call_request(digest: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "request-1",
        "method": "tools/call",
        "protocolVersion": PROTOCOL_VERSION,
        "catalogDigest": digest,
        "params": {
            "name": "cases.close",
            "arguments": {
                "actionId": "close-case-1",
                "parameters": {"status": "closed"},
                "preconditions": {"version": 7},
                "idempotencyKey": "case-1:close",
            },
        },
    }


def test_scoped_catalog_and_exact_tool_call_construct_bounded_action() -> None:
    catalog = NorthboundToolCatalog((tool(),))
    adapter = NorthboundActionAdapter(catalog)
    listed = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": "list-1",
            "method": "tools/list",
            "protocolVersion": PROTOCOL_VERSION,
        },
        identity(),
    )
    assert [item["name"] for item in listed["result"]["tools"]] == ["cases.close"]
    assert "allowedAgents" not in listed["result"]["tools"][0]
    outsider = adapter.handle(
        {
            "jsonrpc": "2.0",
            "id": "list-2",
            "method": "tools/list",
            "protocolVersion": PROTOCOL_VERSION,
        },
        identity("agent.outsider"),
    )
    assert outsider["result"]["tools"] == []
    action = adapter.to_action_plan(call_request(catalog.digest), identity())
    assert (action.source_id, action.asset_id, action.operation) == (
        "case.actions",
        "cases",
        "close-case",
    )
    assert action.approval_mode is ApprovalMode.HUMAN


def test_catalog_rug_pull_and_overbroad_envelope_are_rejected() -> None:
    original = NorthboundToolCatalog((tool(),))
    changed = NorthboundToolCatalog((replace(tool(), description="Delete all case history"),))
    response = NorthboundActionAdapter(changed).handle(call_request(original.digest), identity())
    assert response["error"]["code"] == -32010
    overbroad = {**call_request(original.digest), "shell": "forbidden"}
    response = NorthboundActionAdapter(original).handle(overbroad, identity())
    assert response["error"]["code"] == -32600
