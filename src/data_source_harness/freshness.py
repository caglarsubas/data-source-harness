"""Freshness SLO evaluation and monotonic checkpoint tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .models import CheckpointToken


class FreshnessBreachAction(StrEnum):
    EXCLUDE = "exclude"
    DEGRADE = "degrade"
    REFUSE = "refuse"


@dataclass(frozen=True)
class FreshnessSLO:
    max_age: timedelta
    on_breach: FreshnessBreachAction = FreshnessBreachAction.EXCLUDE

    def __post_init__(self) -> None:
        if self.max_age <= timedelta(0):
            raise ValueError("freshness max_age must be positive")


@dataclass(frozen=True)
class FreshnessObservation:
    source_id: str
    asset_id: str
    observed_at: datetime
    source_event_time: datetime
    watermark: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.asset_id or not self.watermark:
            raise ValueError("freshness observation requires source, asset and watermark")
        if self.observed_at.tzinfo is None or self.source_event_time.tzinfo is None:
            raise ValueError("freshness timestamps must be timezone-aware")
        if self.source_event_time > self.observed_at:
            raise ValueError("source event time cannot be later than observation time")

    def age_at(self, at: datetime) -> timedelta:
        if at.tzinfo is None:
            raise ValueError("evaluation time must be timezone-aware")
        return at - self.source_event_time


@dataclass(frozen=True)
class FreshnessAssessment:
    source_id: str
    asset_id: str
    fresh: bool
    age_ms: int
    watermark: str
    action: FreshnessBreachAction | None


class FreshnessRegistry:
    def __init__(self) -> None:
        self._observations: dict[tuple[str, str], FreshnessObservation] = {}

    def record(self, observation: FreshnessObservation) -> None:
        key = (observation.source_id, observation.asset_id)
        previous = self._observations.get(key)
        if previous and observation.observed_at < previous.observed_at:
            raise ValueError("freshness observations must be recorded monotonically")
        self._observations[key] = observation

    def assess(
        self, source_id: str, asset_id: str, slo: FreshnessSLO, at: datetime
    ) -> FreshnessAssessment:
        observation = self._observations.get((source_id, asset_id))
        if observation is None:
            return FreshnessAssessment(
                source_id,
                asset_id,
                False,
                -1,
                "missing",
                slo.on_breach,
            )
        age = observation.age_at(at)
        fresh = timedelta(0) <= age <= slo.max_age
        return FreshnessAssessment(
            source_id,
            asset_id,
            fresh,
            int(age.total_seconds() * 1000),
            observation.watermark,
            None if fresh else slo.on_breach,
        )


class CheckpointRegression(ValueError):
    pass


class CheckpointLedger:
    """Tracks opaque tokens using caller-supplied monotonic numeric positions."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], CheckpointToken] = {}

    def record(self, token: CheckpointToken) -> None:
        key = (token.source_id, token.stream_id)
        previous = self._tokens.get(key)
        try:
            position = int(token.position)
            previous_position = int(previous.position) if previous else None
        except ValueError as exc:
            raise ValueError("the v1 checkpoint ledger requires an integer position") from exc
        if previous and token.connector_version != previous.connector_version:
            raise CheckpointRegression("connector version changed; explicit migration is required")
        if previous_position is not None and position < previous_position:
            raise CheckpointRegression("checkpoint position regressed")
        if previous and token.observed_at < previous.observed_at:
            raise CheckpointRegression("checkpoint observation time regressed")
        self._tokens[key] = token

    def resume(self, source_id: str, stream_id: str) -> CheckpointToken | None:
        return self._tokens.get((source_id, stream_id))
