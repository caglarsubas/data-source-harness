from __future__ import annotations

import pytest

from data_source_harness.actions import ApprovalMode
from data_source_harness.delegation import A2AActionDelegationAdapter, DelegationRejected
from data_source_harness.policy import RequestIdentity


def identity() -> RequestIdentity:
    return RequestIdentity("org", "solution", "agent.service", "request", "trace", "policy:v1")


def envelope() -> dict[str, object]:
    return {
        "protocol": "a2a/1.0",
        "taskId": "task-1",
        "requestingAgent": "agent.service",
        "sourceAction": {
            "actionId": "act-1",
            "sourceId": "lab.erp",
            "assetId": "orders",
            "operation": "update-status",
            "parameters": {"status": "closed"},
            "preconditions": {"version": 7},
            "idempotencyKey": "task-1:update",
            "risk": "high",
            "approvalMode": "human",
            "purpose": "approved service closure",
            "compensation": None,
        },
    }


def test_a2a_adapter_maps_only_allowlisted_bounded_actions() -> None:
    adapter = A2AActionDelegationAdapter(frozenset({("lab.erp", "update-status")}))
    plan = adapter.to_action_plan(envelope(), identity())
    assert plan.source_id == "lab.erp"
    assert plan.approval_mode is ApprovalMode.HUMAN


def test_a2a_adapter_rejects_identity_mismatch_and_extra_fields() -> None:
    adapter = A2AActionDelegationAdapter(frozenset({("lab.erp", "update-status")}))
    mismatched = envelope()
    mismatched["requestingAgent"] = "agent.other"
    with pytest.raises(DelegationRejected):
        adapter.to_action_plan(mismatched, identity())
    overbroad = envelope()
    overbroad["shell"] = "unsafe"
    with pytest.raises(DelegationRejected):
        adapter.to_action_plan(overbroad, identity())
