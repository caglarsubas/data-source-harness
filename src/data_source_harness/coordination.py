"""Reusable cross-source execution with explicit coverage and provenance."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from .coverage import CoverageExclusion, CoverageStatement, SourceCoverage
from .models import DataBatch, LineageRef, QueryRequest, SearchHit, SearchRequest
from .policy import RequestIdentity
from .runtime import HarnessGateway


@dataclass(frozen=True)
class QueryStep:
    step_id: str
    request: QueryRequest

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("query step identity is required")


@dataclass(frozen=True)
class SearchStep:
    step_id: str
    request: SearchRequest
    asset_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.step_id or not self.asset_ids or any(not item for item in self.asset_ids):
            raise ValueError("search step identity and expected assets are required")


@dataclass(frozen=True)
class SourceExecutionPlan:
    request_id: str
    generated_at: datetime
    query_steps: tuple[QueryStep, ...] = ()
    search_steps: tuple[SearchStep, ...] = ()

    def __post_init__(self) -> None:
        steps = (*self.query_steps, *self.search_steps)
        if not self.request_id or self.generated_at.tzinfo is None or not steps:
            raise ValueError("execution plan requires identity, time and at least one step")
        identifiers = [step.step_id for step in steps]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("cross-source step identities must be unique")

    @property
    def expected_sources(self) -> frozenset[str]:
        return frozenset(
            [step.request.source_id for step in self.query_steps]
            + [step.request.source_id for step in self.search_steps]
        )


@dataclass(frozen=True)
class StepResult:
    step_id: str
    source_id: str
    asset_ids: tuple[str, ...]
    batches: tuple[DataBatch, ...] = ()
    hits: tuple[SearchHit, ...] = ()

    @property
    def lineage(self) -> tuple[LineageRef, ...]:
        return tuple(lineage for batch in self.batches for lineage in batch.lineage) + tuple(
            lineage for hit in self.hits for lineage in hit.lineage
        )


@dataclass(frozen=True)
class CoordinationResult:
    request_id: str
    steps: tuple[StepResult, ...]
    coverage: CoverageStatement
    lineage: tuple[LineageRef, ...]

    @property
    def complete(self) -> bool:
        return self.coverage.is_complete

    def step(self, step_id: str) -> StepResult:
        try:
            return next(step for step in self.steps if step.step_id == step_id)
        except StopIteration as exc:
            raise KeyError(f"unknown coordination step: {step_id}") from exc


class CrossSourceCoordinator:
    """Execute independent source steps concurrently and report every omission."""

    def __init__(self, gateway: HarnessGateway) -> None:
        self.gateway = gateway

    async def execute(
        self, plan: SourceExecutionPlan, identity: RequestIdentity
    ) -> CoordinationResult:
        if plan.request_id != identity.request_id:
            raise ValueError("execution plan and request identity must match")
        operations = [self._query(step, identity) for step in plan.query_steps] + [
            self._search(step, identity) for step in plan.search_steps
        ]
        outcomes = await asyncio.gather(*operations, return_exceptions=True)
        successful: list[StepResult] = []
        failures: dict[str, list[str]] = {}
        step_sources = [step.request.source_id for step in plan.query_steps] + [
            step.request.source_id for step in plan.search_steps
        ]
        for source_id, outcome in zip(step_sources, outcomes, strict=True):
            if isinstance(outcome, asyncio.CancelledError):
                raise outcome
            if isinstance(outcome, BaseException):
                failures.setdefault(source_id, []).append(type(outcome).__name__)
            else:
                successful.append(outcome)

        completed_by_source: dict[str, set[str]] = {}
        for result in successful:
            completed_by_source.setdefault(result.source_id, set()).update(result.asset_ids)
        included = tuple(
            SourceCoverage(source_id, tuple(sorted(asset_ids)), True)
            for source_id, asset_ids in sorted(completed_by_source.items())
            if source_id not in failures
        )
        excluded = tuple(
            CoverageExclusion(
                source_id,
                "source_execution_failed",
                ",".join(sorted(set(error_types))),
            )
            for source_id, error_types in sorted(failures.items())
        )
        coverage = CoverageStatement(
            plan.request_id,
            plan.generated_at,
            included,
            excluded,
            plan.expected_sources,
        )
        lineage = self._unique_lineage(
            tuple(item for result in successful for item in result.lineage)
        )
        return CoordinationResult(plan.request_id, tuple(successful), coverage, lineage)

    async def _query(self, step: QueryStep, identity: RequestIdentity) -> StepResult:
        batches = tuple([batch async for batch in self.gateway.execute(step.request, identity)])
        return StepResult(
            step.step_id,
            step.request.source_id,
            step.request.asset_ids,
            batches=batches,
        )

    async def _search(self, step: SearchStep, identity: RequestIdentity) -> StepResult:
        hits = await self.gateway.search(step.request, identity)
        return StepResult(
            step.step_id,
            step.request.source_id,
            step.asset_ids,
            hits=hits,
        )

    @staticmethod
    def _unique_lineage(values: tuple[LineageRef, ...]) -> tuple[LineageRef, ...]:
        found: dict[tuple[str, str, str | None, str | None], LineageRef] = {}
        for item in values:
            key = (item.source_id, item.asset_id, item.record_id, item.field_path)
            found[key] = item
        return tuple(
            found[key] for key in sorted(found, key=lambda item: tuple(x or "" for x in item))
        )
