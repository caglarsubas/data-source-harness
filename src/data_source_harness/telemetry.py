"""Tenant-neutral, sink-agnostic evidence events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from .models import Scalar
from .policy import RequestIdentity


@dataclass(frozen=True)
class TelemetryEvent:
    name: str
    identity: RequestIdentity
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    attributes: dict[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.startswith("data.harness."):
            raise ValueError("telemetry names must use the data.harness namespace")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        forbidden = ("credential", "password", "secret", "token")
        if any(fragment in key.lower() for key in self.attributes for fragment in forbidden):
            raise ValueError("telemetry cannot contain credential material")


class TelemetrySink(Protocol):
    async def emit(self, event: TelemetryEvent) -> None: ...


class NoopTelemetrySink:
    async def emit(self, event: TelemetryEvent) -> None:
        return None


class MemoryTelemetrySink:
    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    async def emit(self, event: TelemetryEvent) -> None:
        self.events.append(event)
