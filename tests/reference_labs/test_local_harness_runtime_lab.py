from datetime import datetime

import pytest

from data_source_harness.connector import Capability
from data_source_harness.policy import AuthorizationRequest
from reference_labs.white_goods.live.connectors import _json_value, _secret, _version
from reference_labs.white_goods.live.harness_probe import LocalReadPolicy, _identity


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
