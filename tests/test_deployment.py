import pytest

from data_source_harness.deployment import (
    DeploymentMode,
    DeploymentProfile,
    EgressDenied,
    EgressGuard,
)


def airgap() -> DeploymentProfile:
    return DeploymentProfile(
        "airgap", DeploymentMode.AIR_GAPPED, frozenset({"model-plane.ai.svc"}), False, False, True
    )


def test_airgap_profile_rejects_external_telemetry() -> None:
    with pytest.raises(ValueError, match="external telemetry"):
        DeploymentProfile("bad", DeploymentMode.AIR_GAPPED, frozenset(), False, True, True)


def test_airgap_egress_is_allowlist_only() -> None:
    guard = EgressGuard(airgap())
    guard.authorize("http://model-plane.ai.svc/v1/embeddings")
    guard.authorize("http://127.0.0.1:8080/health")
    with pytest.raises(EgressDenied, match="not permitted"):
        guard.authorize("https://api.external.example/v1")
    with pytest.raises(EgressDenied, match="credentials"):
        guard.authorize("https://user:password@model-plane.ai.svc/v1/embeddings")


def test_local_laptop_profile_allows_only_local_services_and_loopback() -> None:
    profile = DeploymentProfile(
        "laptop",
        DeploymentMode.LOCAL_LAPTOP,
        frozenset({"postgresql", "model-plane"}),
        True,
        False,
        False,
    )
    guard = EgressGuard(profile)
    guard.authorize("http://postgresql:5432/health")
    guard.authorize("http://localhost:8080/health")
    with pytest.raises(EgressDenied, match="not permitted"):
        guard.authorize("https://console.cloud.google.com/")


def test_local_laptop_profile_rejects_telemetry_and_mirror() -> None:
    with pytest.raises(ValueError, match="external telemetry"):
        DeploymentProfile("bad", DeploymentMode.LOCAL_LAPTOP, frozenset(), True, True, False)
    with pytest.raises(ValueError, match="preloaded images"):
        DeploymentProfile("bad", DeploymentMode.LOCAL_LAPTOP, frozenset(), True, False, True)
    with pytest.raises(ValueError, match="single-label service hosts"):
        DeploymentProfile(
            "bad",
            DeploymentMode.LOCAL_LAPTOP,
            frozenset({"api.external.example"}),
            True,
            False,
            False,
        )
