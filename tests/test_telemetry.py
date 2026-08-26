import pytest

from data_source_harness.policy import RequestIdentity
from data_source_harness.telemetry import TelemetryEvent

IDENTITY = RequestIdentity("org", "solution", "agent", "request", "trace", "sha256:policy")


def test_telemetry_namespace_is_neutral() -> None:
    with pytest.raises(ValueError, match="data.harness"):
        TelemetryEvent("whitegoods.query", IDENTITY)


def test_telemetry_rejects_secret_fields() -> None:
    with pytest.raises(ValueError, match="credential"):
        TelemetryEvent("data.harness.query", IDENTITY, attributes={"access_token": "do-not-log"})
