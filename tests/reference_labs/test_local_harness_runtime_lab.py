from datetime import datetime

import pytest

from data_source_harness.connector import Capability
from data_source_harness.policy import AuthorizationRequest
from reference_labs.white_goods.live.connectors import (
    PostgreSQLLiveConnector,
    _json_value,
    _secret,
    _version,
)
from reference_labs.white_goods.live.harness_probe import (
    LocalMutationPolicy,
    LocalReadPolicy,
    _identity,
    _mutation_identity,
)


def test_live_connector_helpers_keep_credentials_out_of_contracts(tmp_path) -> None:
    credential = tmp_path / "credential"
    credential.write_text("local-only-secret\n", encoding="utf-8")
    assert _secret(credential) == "local-only-secret"
    credential.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        _secret(credential)
    assert _json_value(datetime.fromisoformat("2026-08-28T00:00:00+00:00")) == (
        "2026-08-28T00:00:00+00:00"
    )
    assert _version("whitegoods.test", [{"id": 1}]).version.startswith("sha256:")


async def test_local_read_policy_allows_only_tenant_bound_reads() -> None:
    policy = LocalReadPolicy()
    allowed = await policy.evaluate(
        AuthorizationRequest(
            _identity(),
            "whitegoods.erp",
            Capability.QUERY,
            ("service_orders",),
            "diagnosis",
        )
    )
    denied = await policy.evaluate(
        AuthorizationRequest(
            _identity(),
            "whitegoods.erp",
            Capability.MUTATE,
            ("service_orders",),
            "change source",
        )
    )
    assert allowed.allowed
    assert not denied.allowed


async def test_postgresql_live_connector_exposes_only_governed_mutation() -> None:
    connector = PostgreSQLLiveConnector(
        host="postgresql",
        database="whitegoods",
        user_file="/run/secrets/postgres-user",
        password_file="/run/secrets/postgres-password",
    )
    assert Capability.MUTATE in connector.profile.capabilities
    assert connector.profile.consistency.supports_version_precondition
    assert connector.profile.consistency.supports_idempotency_key
    assert connector.profile.consistency.supports_transactions
    with pytest.raises(PermissionError, match="operation"):
        await connector.mutate(
            {
                "action_id": "unsafe",
                "asset_id": "service_orders",
                "operation": "delete-service-order",
                "parameters": {"serviceOrderId": "SO1001", "resolution": "x"},
                "preconditions": {
                    "recordVersion": 1,
                    "expectedResolution": "replaced drain pump",
                },
                "idempotency_key": "unsafe",
            }
        )


async def test_local_mutation_policy_is_operation_and_asset_bound() -> None:
    policy = LocalMutationPolicy()
    allowed = await policy.evaluate(
        AuthorizationRequest(
            _mutation_identity(),
            "whitegoods.erp",
            Capability.MUTATE,
            ("service_orders",),
            "supervised change",
            {"stage": "execute"},
            {"operation": "resolve-service-order"},
        )
    )
    denied = await policy.evaluate(
        AuthorizationRequest(
            _mutation_identity(),
            "whitegoods.erp",
            Capability.MUTATE,
            ("customers",),
            "unsafe change",
            {"stage": "execute"},
            {"operation": "delete-customer"},
        )
    )
    assert allowed.allowed
    assert not denied.allowed
