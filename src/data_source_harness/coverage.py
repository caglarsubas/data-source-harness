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

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id is required")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")
        if not self.included and not self.excluded:
            raise ValueError("coverage must explicitly include or exclude at least one source")
        included_ids = {item.source_id for item in self.included}
        excluded_ids = {item.source_id for item in self.excluded}
        overlap = included_ids & excluded_ids
        if overlap:
            raise ValueError(f"a source cannot be both included and excluded: {sorted(overlap)}")

    @property
    def is_complete(self) -> bool:
        return not self.excluded and all(source.complete for source in self.included)
