"""Grounded answer envelope with mandatory route, coverage and provenance."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .coverage import CoverageStatement
from .models import LineageRef
from .routing import RouteDecision, RouteStatus


class ContextOutcome(StrEnum):
    ANSWER = "answer"
    REFUSAL = "refusal"
    ESCALATION = "escalation"


@dataclass(frozen=True)
class ContextEnvelope:
    request_id: str
    outcome: ContextOutcome
    content: str | None
    route: RouteDecision
    coverage: CoverageStatement
    lineage: tuple[LineageRef, ...]
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.request_id or self.request_id != self.route.request_id:
            raise ValueError("context and route request identities must match")
        if self.request_id != self.coverage.request_id:
            raise ValueError("context and coverage request identities must match")
        if self.outcome is ContextOutcome.ANSWER:
            if not self.content or not self.route.complete or not self.coverage.is_complete:
                raise ValueError("answers require content, a complete route and complete coverage")
            if not self.lineage:
                raise ValueError("answers require exact provenance")
        else:
            if self.content is not None or not self.reason_codes:
                raise ValueError("refusal/escalation requires reasons and no answer content")
            expected = (
                RouteStatus.ESCALATION_REQUIRED
                if self.outcome is ContextOutcome.ESCALATION
                else RouteStatus.REFUSED
            )
            if self.route.status is not expected:
                raise ValueError("context outcome must match route status")
