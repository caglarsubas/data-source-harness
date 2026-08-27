"""Machine-readable statements about what a result did and did not cover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CoverageExclusion:
    source_id: str
    reason_code: str
    detail: str

    def __post_init__(self) -> None:
        if not self.source_id or not self.reason_code or not self.detail:
            raise ValueError("coverage exclusions require source, reason and detail")


@dataclass(frozen=True)
class SourceCoverage:
    source_id: str
    asset_ids: tuple[str, ...]
    complete: bool
    watermark: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.asset_ids:
            raise ValueError("source coverage requires a source and at least one asset")
        if len(set(self.asset_ids)) != len(self.asset_ids):
            raise ValueError("covered asset_ids must be unique")


@dataclass(frozen=True)
class CoverageStatement:
    request_id: str
    generated_at: datetime
    included: tuple[SourceCoverage, ...]
    excluded: tuple[CoverageExclusion, ...] = ()
    expected_sources: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id is required")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if not self.included and not self.excluded:
            raise ValueError("coverage must explicitly include or exclude at least one source")
        included_ids = {item.source_id for item in self.included}
        excluded_ids = {item.source_id for item in self.excluded}
        if len(included_ids) != len(self.included) or len(excluded_ids) != len(self.excluded):
            raise ValueError("coverage may mention each source only once")
        overlap = included_ids & excluded_ids
        if overlap:
            raise ValueError(f"a source cannot be both included and excluded: {sorted(overlap)}")
        if any(not source_id for source_id in self.expected_sources):
            raise ValueError("expected source identities must be non-empty")
        observed = included_ids | excluded_ids
        if self.expected_sources and not observed.issubset(self.expected_sources):
            raise ValueError("coverage contains a source outside the expected universe")

    @property
    def is_complete(self) -> bool:
        included_ids = {source.source_id for source in self.included}
        universe_complete = not self.expected_sources or included_ids == self.expected_sources
        return (
            universe_complete
            and not self.excluded
            and bool(self.included)
            and all(source.complete for source in self.included)
        )
