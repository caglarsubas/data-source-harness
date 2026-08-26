"""Canonical, source-neutral data exchange objects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

Scalar = str | int | float | bool | None


def utc_now() -> datetime:
    return datetime.now(UTC)


class BatchKind(StrEnum):
    ARROW = "arrow"
    DOCUMENT = "document"
    GRAPH = "graph"
    EVENT = "event"
    BINARY = "binary"


@dataclass(frozen=True)
class SourceVersion:
    source_id: str
    version: str
    observed_at: datetime
    effective_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.version:
            raise ValueError("source_id and version are required")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.effective_at is not None and self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")


@dataclass(frozen=True)
class LineageRef:
    source_id: str
    asset_id: str
    record_id: str | None = None
    field_path: str | None = None


@dataclass(frozen=True)
class AssetRef:
    source_id: str
    asset_id: str


@dataclass(frozen=True)
class Asset:
    ref: AssetRef
    name: str
    kind: str
    description: str | None = None
    metadata: Mapping[str, Scalar] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldSchema:
    name: str
    logical_type: str
    nullable: bool = True
    description: str | None = None
    metadata: Mapping[str, Scalar] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetSchema:
    asset: AssetRef
    fields: tuple[FieldSchema, ...]
    version: SourceVersion


@dataclass(frozen=True)
class Document:
    document_id: str
    source_id: str
    asset_id: str
    canonical_uri: str
    mime_type: str
    content: str
    acl_principals: tuple[str, ...]
    source_version: SourceVersion
    content_hash: str
    metadata: Mapping[str, Scalar] = field(default_factory=dict)
    lineage: tuple[LineageRef, ...] = ()

    def __post_init__(self) -> None:
        required = (
            self.document_id,
            self.source_id,
            self.asset_id,
            self.canonical_uri,
            self.mime_type,
            self.content_hash,
        )
        if any(not value for value in required):
            raise ValueError("document identity, source, URI, MIME type and hash are required")
        if not self.acl_principals:
            raise ValueError("document ACLs must be captured with content")


@dataclass(frozen=True)
class ChangeEvent:
    event_id: str
    source_id: str
    asset_id: str
    operation: str
    observed_at: datetime
    payload: Mapping[str, Any]
    checkpoint: str | None = None
    tombstone: bool = False


@dataclass(frozen=True)
class DataBatch:
    kind: BatchKind
    payload: Any
    source_versions: tuple[SourceVersion, ...]
    lineage: tuple[LineageRef, ...]
    row_count: int | None = None
    byte_count: int | None = None

    def __post_init__(self) -> None:
        if not self.source_versions or not self.lineage:
            raise ValueError("every batch requires source version and lineage")
        if self.row_count is not None and self.row_count < 0:
            raise ValueError("row_count cannot be negative")
        if self.byte_count is not None and self.byte_count < 0:
            raise ValueError("byte_count cannot be negative")


@dataclass(frozen=True)
class QueryRequest:
    source_id: str
    asset_ids: tuple[str, ...]
    plan: Mapping[str, Any]
    limit: int
    deadline_ms: int
    purpose: str

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("query limit must be positive")
        if self.deadline_ms <= 0:
            raise ValueError("deadline_ms must be positive")
        if not self.purpose.strip():
            raise ValueError("purpose is required")


@dataclass(frozen=True)
class SearchRequest:
    source_id: str
    query: str
    top_k: int
    filters: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.query.strip() or self.top_k <= 0:
            raise ValueError("search query and positive top_k are required")


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    asset_id: str
    record_id: str
    fusion_score: float
    source_version: SourceVersion
    lineage: tuple[LineageRef, ...]
    lexical_score: float | None = None
    dense_score: float | None = None
    sparse_score: float | None = None
    reranker_score: float | None = None
    acl_decision_id: str | None = None


@dataclass(frozen=True)
class CheckpointToken:
    source_id: str
    stream_id: str
    position: str
    observed_at: datetime
    connector_version: str

    def __post_init__(self) -> None:
        if any(
            not value
            for value in (
                self.source_id,
                self.stream_id,
                self.position,
                self.connector_version,
            )
        ):
            raise ValueError("checkpoint identity, position and connector version are required")
        if self.observed_at.tzinfo is None:
            raise ValueError("checkpoint observed_at must be timezone-aware")
