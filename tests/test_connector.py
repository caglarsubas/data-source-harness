import pytest

from data_source_harness.connector import Capability, ConnectorRegistry, UnsupportedCapability

from .helpers import FakeConnector


def test_registry_rejects_duplicate_identity() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeConnector())


def test_registry_negotiates_capability_before_invocation() -> None:
    registry = ConnectorRegistry()
    registry.register(FakeConnector())
    with pytest.raises(UnsupportedCapability):
        registry.get("lab.postgresql", Capability.MUTATE)
