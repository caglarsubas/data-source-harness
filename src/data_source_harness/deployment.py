"""Deployment constraints, including fail-closed air-gap egress enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlparse


class DeploymentMode(StrEnum):
    CONNECTED = "connected"
    SELF_HOSTED = "self-hosted"
    AIR_GAPPED = "air-gapped"


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: str
    mode: DeploymentMode
    allowed_hosts: frozenset[str]
    dns_enabled: bool
    external_telemetry: bool
    artifact_mirror_required: bool

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id is required")
        if self.mode is DeploymentMode.AIR_GAPPED:
            if self.dns_enabled or self.external_telemetry:
                raise ValueError("air-gapped profiles cannot enable DNS or external telemetry")
            if not self.artifact_mirror_required:
                raise ValueError("air-gapped profiles require an internal artifact mirror")


class EgressDenied(PermissionError):
    pass


class EgressGuard:
    """Explicit allow-list; air-gapped mode never guesses whether a host is internal."""

    def __init__(self, profile: DeploymentProfile) -> None:
        self.profile = profile

    def authorize(self, endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise EgressDenied("endpoint must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise EgressDenied("endpoint must not contain credentials or fragments")
        host = parsed.hostname.lower()
        if host in {item.lower() for item in self.profile.allowed_hosts}:
            return
        if self.profile.mode is DeploymentMode.CONNECTED:
            return
        if host == "localhost" or self._is_loopback(host):
            return
        raise EgressDenied(f"host is not permitted by deployment profile: {host}")

    @staticmethod
    def _is_loopback(host: str) -> bool:
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False
