"""Executable connector conformance checks for reference-lab promotion."""

from __future__ import annotations

from dataclasses import dataclass

from .connector import Connector


@dataclass(frozen=True)
class ConformanceCheck:
    check_id: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ConformanceReport:
    connector_id: str
    checks: tuple[ConformanceCheck, ...]

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


async def run_connector_conformance(connector: Connector) -> ConformanceReport:
    checks: list[ConformanceCheck] = []
    profile = connector.profile
    checks.append(ConformanceCheck("profile.valid", True, profile.sdk_api))

    health = await connector.health()
    checks.append(
        ConformanceCheck(
            "health.healthy",
            health.healthy,
            health.observed_version,
        )
    )
    first = await connector.discover()
    second = await connector.discover()
    checks.append(
        ConformanceCheck(
            "discovery.deterministic",
            first == second,
            f"first={len(first)}, second={len(second)}",
        )
    )
    refs = [asset.ref for asset in first]
    checks.append(
        ConformanceCheck(
            "discovery.unique_identity",
            len(refs) == len(set(refs)),
            f"assets={len(refs)}",
        )
    )
    descriptions_ok = True
    detail = "no assets"
    if first:
        schemas = [await connector.describe(asset.ref) for asset in first]
        descriptions_ok = all(
            schema.asset == asset.ref for schema, asset in zip(schemas, first, strict=True)
        )
        detail = f"schemas={len(schemas)}"
    checks.append(ConformanceCheck("describe.matches_asset", descriptions_ok, detail))
    return ConformanceReport(profile.connector_id, tuple(checks))
