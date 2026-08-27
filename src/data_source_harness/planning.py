"""Bounded query planning and field/relationship authorization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .models import QueryRequest, Scalar


@dataclass(frozen=True)
class RelationshipRef:
    left_asset: str
    left_field: str
    right_asset: str
    right_field: str

    @property
    def relationship_id(self) -> str:
        return f"{self.left_asset}.{self.left_field}->{self.right_asset}.{self.right_field}"


@dataclass(frozen=True)
class QueryIntent:
    source_id: str
    asset_ids: tuple[str, ...]
    fields: Mapping[str, tuple[str, ...]]
    filters: Mapping[str, Mapping[str, Scalar]]
    relationships: tuple[RelationshipRef, ...]
    limit: int
    deadline_ms: int
    purpose: str


@dataclass(frozen=True)
class PlanningConstraints:
    allowed_fields: Mapping[str, frozenset[str]]
    allowed_relationships: frozenset[str]
    max_assets: int
    max_rows: int
    max_deadline_ms: int

    def __post_init__(self) -> None:
        if min(self.max_assets, self.max_rows, self.max_deadline_ms) <= 0:
            raise ValueError("planning bounds must be positive")


@dataclass(frozen=True)
class BoundedQueryPlan:
    source_id: str
    asset_ids: tuple[str, ...]
    fields: Mapping[str, tuple[str, ...]]
    filters: Mapping[str, Mapping[str, Scalar]]
    relationships: tuple[RelationshipRef, ...]
    limit: int
    deadline_ms: int
    purpose: str
    estimated_rows: int

    def to_query_request(
        self, policy_attributes: Mapping[str, Scalar] | None = None
    ) -> QueryRequest:
        return QueryRequest(
            self.source_id,
            self.asset_ids,
            {
                "select_by_asset": {key: list(value) for key, value in self.fields.items()},
                "where_by_asset": {
                    asset_id: dict(values) for asset_id, values in self.filters.items()
                },
                "relationships": [item.relationship_id for item in self.relationships],
                "estimated_rows": self.estimated_rows,
            },
            self.limit,
            self.deadline_ms,
            self.purpose,
            policy_attributes or {},
        )


class PlanDenied(PermissionError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(f"bounded plan denied: {reason_code}")
        self.reason_code = reason_code


class BoundedQueryPlanner:
    def compile(self, intent: QueryIntent, constraints: PlanningConstraints) -> BoundedQueryPlan:
        if not intent.source_id or not intent.asset_ids or not intent.purpose:
            raise ValueError("query intent identity, assets and purpose are required")
        if len(intent.asset_ids) > constraints.max_assets:
            raise PlanDenied("asset_bound_exceeded")
        if intent.limit <= 0 or intent.limit > constraints.max_rows:
            raise PlanDenied("row_bound_exceeded")
        if intent.deadline_ms <= 0 or intent.deadline_ms > constraints.max_deadline_ms:
            raise PlanDenied("deadline_bound_exceeded")
        if set(intent.fields) != set(intent.asset_ids):
            raise PlanDenied("field_scope_incomplete")
        for asset_id, fields in intent.fields.items():
            allowed = constraints.allowed_fields.get(asset_id, frozenset())
            if not set(fields).issubset(allowed):
                raise PlanDenied("field_not_authorized")
        if not set(intent.filters).issubset(intent.asset_ids):
            raise PlanDenied("filter_outside_asset_scope")
        for asset_id, filters in intent.filters.items():
            if not set(filters).issubset(constraints.allowed_fields.get(asset_id, frozenset())):
                raise PlanDenied("filter_field_not_authorized")
        for relationship in intent.relationships:
            if relationship.relationship_id not in constraints.allowed_relationships:
                raise PlanDenied("relationship_not_authorized")
            if (
                relationship.left_asset not in intent.asset_ids
                or relationship.right_asset not in intent.asset_ids
            ):
                raise PlanDenied("relationship_outside_asset_scope")
        return BoundedQueryPlan(
            intent.source_id,
            intent.asset_ids,
            dict(intent.fields),
            dict(intent.filters),
            intent.relationships,
            intent.limit,
            intent.deadline_ms,
            intent.purpose,
            intent.limit,
        )
