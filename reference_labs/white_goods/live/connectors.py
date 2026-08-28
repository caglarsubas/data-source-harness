"""Bounded connectors used by the laptop-local Phase 7 runtime lab.

The implementations deliberately expose a small, read-only surface.  They use
the same connector contracts and gateway as production code while keeping all
credentials in mounted secret files and every endpoint on the internal Compose
network.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    DataModel,
    HealthStatus,
    RuntimeMode,
)
from data_source_harness.models import (
    Asset,
    AssetRef,
    AssetSchema,
    BatchKind,
    DataBatch,
    FieldSchema,
    LineageRef,
    QueryRequest,
    SourceVersion,
)


def _secret(path: str | Path) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"credential reference is empty: {path}")
    return value


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def _version(source_id: str, payload: Any) -> SourceVersion:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return SourceVersion(
        source_id, f"sha256:{hashlib.sha256(encoded).hexdigest()}", datetime.now(UTC)
    )


def _profile(
    connector_id: str,
    model: DataModel,
    *,
    max_result_bytes: int = 2 * 1024 * 1024,
) -> ConnectorProfile:
    return ConnectorProfile(
        connector_id,
        "1.0.0",
        "harness.connector/v1",
        RuntimeMode.CONTAINER,
        frozenset({model}),
        frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
        frozenset({"credential-reference"}),
        limits=ConnectorLimits(max_parallelism=1, max_result_bytes=max_result_bytes),
        metadata={"networkBoundary": "compose-internal", "mutationMode": "disabled"},
    )


class PostgreSQLLiveConnector:
    """Read-only PostgreSQL discovery and bounded projection/filter execution."""

    source_id = "whitegoods.erp"

    def __init__(self, *, host: str, database: str, user_file: str, password_file: str) -> None:
        self.host = host
        self.database = database
        self.user_file = user_file
        self.password_file = password_file
        self.profile = _profile(self.source_id, DataModel.TABULAR)

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(
            host=self.host,
            dbname=self.database,
            user=_secret(self.user_file),
            password=_secret(self.password_file),
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=5000",
        )

    async def health(self) -> HealthStatus:
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version')")
            return HealthStatus(True, str(cursor.fetchone()[0]), ("read-only",))

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        if cursor is not None:
            raise ValueError("PostgreSQL discovery does not accept a cursor")
        with self._connect() as connection, connection.cursor() as db_cursor:
            db_cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
            return tuple(
                Asset(AssetRef(self.source_id, row[0]), row[0], "table")
                for row in db_cursor.fetchall()
            )

    async def describe(self, asset: AssetRef) -> AssetSchema:
        if asset.source_id != self.source_id:
            raise ValueError("asset does not belong to PostgreSQL connector")
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
                (asset.asset_id,),
            )
            fields = tuple(
                FieldSchema(str(name), str(logical_type), nullable == "YES")
                for name, logical_type, nullable in cursor.fetchall()
            )
        if not fields:
            raise KeyError(f"unknown PostgreSQL asset: {asset.asset_id}")
        return AssetSchema(
            asset, fields, _version(self.source_id, [field.name for field in fields])
        )

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        from psycopg import sql

        if request.source_id != self.source_id or len(request.asset_ids) != 1:
            raise ValueError("PostgreSQL execution requires exactly one local asset")
        asset_id = request.asset_ids[0]
        schema = await self.describe(AssetRef(self.source_id, asset_id))
        allowed = {field.name for field in schema.fields}
        selected = tuple(request.plan.get("select_by_asset", {}).get(asset_id, ()))
        filters = dict(request.plan.get("where_by_asset", {}).get(asset_id, {}))
        if not selected or not (set(selected) | set(filters)).issubset(allowed):
            raise PermissionError("PostgreSQL plan contains an unapproved projection or filter")
        predicates = [sql.SQL("{} = %s").format(sql.Identifier(name)) for name in filters]
        statement = sql.SQL("SELECT {} FROM {}{} ORDER BY {} LIMIT %s").format(
            sql.SQL(",").join(map(sql.Identifier, selected)),
            sql.Identifier(asset_id),
            sql.SQL(" WHERE ") + sql.SQL(" AND ").join(predicates) if predicates else sql.SQL(""),
            sql.Identifier(selected[0]),
        )
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute(statement, (*filters.values(), request.limit))
            rows = [
                {name: _json_value(value) for name, value in zip(selected, row, strict=True)}
                for row in cursor.fetchall()
            ]
        version = _version(self.source_id, rows)
        yield DataBatch(
            BatchKind.ARROW,
            rows,
            (version,),
            tuple(LineageRef(self.source_id, asset_id, str(row[selected[0]])) for row in rows),
            row_count=len(rows),
        )


class S3LiveConnector:
    """S3-compatible object discovery plus bounded object metadata snapshots."""

    source_id = "whitegoods.documents"
    bucket = "technical-documents"

    def __init__(self, *, endpoint: str, access_key_file: str, secret_key_file: str) -> None:
        self.endpoint = endpoint
        self.access_key_file = access_key_file
        self.secret_key_file = secret_key_file
        self.profile = _profile(self.source_id, DataModel.DOCUMENT)

    def _client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=_secret(self.access_key_file),
            aws_secret_access_key=_secret(self.secret_key_file),
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 1},
            ),
        )

    async def health(self) -> HealthStatus:
        response = self._client().list_buckets()
        return HealthStatus(
            True, str(response["ResponseMetadata"]["HTTPStatusCode"]), ("read-only",)
        )

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        if cursor is not None:
            raise ValueError("S3 discovery does not accept a cursor")
        buckets = self._client().list_buckets()["Buckets"]
        return tuple(
            Asset(AssetRef(self.source_id, item["Name"]), item["Name"], "bucket")
            for item in sorted(buckets, key=lambda item: item["Name"])
        )

    async def describe(self, asset: AssetRef) -> AssetSchema:
        if asset != AssetRef(self.source_id, self.bucket):
            raise KeyError(f"unknown S3 asset: {asset.asset_id}")
        fields = (
            FieldSchema("key", "string", False),
            FieldSchema("etag", "string", False),
            FieldSchema("size", "integer", False),
            FieldSchema("last_modified", "datetime", False),
        )
        return AssetSchema(asset, fields, _version(self.source_id, [item.name for item in fields]))

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        if request.source_id != self.source_id or request.asset_ids != (self.bucket,):
            raise ValueError("S3 execution is restricted to the technical-documents bucket")
        response = self._client().list_objects_v2(Bucket=self.bucket, MaxKeys=request.limit)
        rows = [
            {
                "key": item["Key"],
                "etag": item["ETag"].strip('"'),
                "size": item["Size"],
                "last_modified": item["LastModified"].isoformat(),
            }
            for item in response.get("Contents", [])
        ]
        version = _version(self.source_id, rows)
        yield DataBatch(
            BatchKind.DOCUMENT,
            rows,
            (version,),
            tuple(LineageRef(self.source_id, self.bucket, row["key"]) for row in rows),
            row_count=len(rows),
        )

    def read_object(self, key: str) -> bytes:
        if key.startswith("/") or ".." in key.split("/"):
            raise PermissionError("unsafe object key")
        return self._client().get_object(Bucket=self.bucket, Key=key)["Body"].read()


class KafkaLiveConnector:
    """Bounded, non-committing snapshot reads from a Kafka-compatible topic."""

    source_id = "whitegoods.telemetry"
    topic = "telemetry"

    def __init__(self, *, bootstrap_servers: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.profile = _profile(self.source_id, DataModel.EVENT)

    def _consumer(self, topic: str | None = None) -> Any:
        from kafka import KafkaConsumer

        return KafkaConsumer(
            *([topic] if topic else []),
            bootstrap_servers=self.bootstrap_servers,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            consumer_timeout_ms=5000,
            request_timeout_ms=6000,
            api_version_auto_timeout_ms=5000,
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )

    async def health(self) -> HealthStatus:
        consumer = self._consumer()
        try:
            topics = consumer.topics()
        finally:
            consumer.close()
        return HealthStatus(self.topic in topics, "kafka-api", ("non-committing",))

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        if cursor is not None:
            raise ValueError("Kafka discovery does not accept a cursor")
        consumer = self._consumer()
        try:
            topics = sorted(name for name in consumer.topics() if not name.startswith("_"))
        finally:
            consumer.close()
        return tuple(Asset(AssetRef(self.source_id, name), name, "topic") for name in topics)

    async def describe(self, asset: AssetRef) -> AssetSchema:
        if asset != AssetRef(self.source_id, self.topic):
            raise KeyError(f"unknown Kafka asset: {asset.asset_id}")
        fields = (
            FieldSchema("event_id", "string", False),
            FieldSchema("event_time", "datetime", False),
            FieldSchema("serial_number", "string"),
            FieldSchema("event_type", "string", False),
            FieldSchema("value", "number", False),
        )
        return AssetSchema(asset, fields, _version(self.source_id, [item.name for item in fields]))

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        if request.source_id != self.source_id or request.asset_ids != (self.topic,):
            raise ValueError("Kafka execution is restricted to the telemetry topic")
        consumer = self._consumer(self.topic)
        rows: list[dict[str, Any]] = []
        offsets: list[str] = []
        try:
            for message in consumer:
                rows.append(message.value)
                offsets.append(f"{message.partition}:{message.offset}")
                if len(rows) >= request.limit:
                    break
        finally:
            consumer.close()
        version = _version(self.source_id, offsets)
        yield DataBatch(
            BatchKind.EVENT,
            rows,
            (version,),
            tuple(
                LineageRef(self.source_id, self.topic, str(row.get("event_id") or index))
                for index, row in enumerate(rows)
            ),
            row_count=len(rows),
        )


class RestLiveConnector:
    """Credential-bound and cursor-bounded REST collection connector."""

    source_id = "whitegoods.service-api"
    asset_id = "appointments"

    def __init__(self, *, base_url: str, credential_file: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.credential_file = credential_file
        self.profile = _profile(self.source_id, DataModel.TABULAR)

    def _get(self, path: str, query: Mapping[str, str] | None = None) -> dict[str, Any]:
        suffix = f"?{urlencode(query)}" if query else ""
        request = Request(
            f"{self.base_url}{path}{suffix}",
            headers={"Authorization": f"Bearer {_secret(self.credential_file)}"},
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    async def health(self) -> HealthStatus:
        with urlopen(f"{self.base_url.removesuffix('/v1')}/health", timeout=3) as response:
            return HealthStatus(response.status == 200, str(response.status), ("read-only",))

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        if cursor is not None:
            raise ValueError("REST discovery does not accept a cursor")
        self._get("/appointments")
        return (Asset(AssetRef(self.source_id, self.asset_id), self.asset_id, "collection"),)

    async def describe(self, asset: AssetRef) -> AssetSchema:
        if asset != AssetRef(self.source_id, self.asset_id):
            raise KeyError(f"unknown REST asset: {asset.asset_id}")
        fields = tuple(
            FieldSchema(name, logical_type, False)
            for name, logical_type in (
                ("appointment_id", "string"),
                ("service_order_id", "string"),
                ("technician_id", "string"),
                ("scheduled_at", "datetime"),
                ("status", "string"),
            )
        )
        return AssetSchema(asset, fields, _version(self.source_id, [item.name for item in fields]))

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        if request.source_id != self.source_id or request.asset_ids != (self.asset_id,):
            raise ValueError("REST execution is restricted to appointments")
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < request.limit:
            query = {"cursor": cursor} if cursor is not None else None
            page = self._get("/appointments", query)
            rows.extend(page["items"][: request.limit - len(rows)])
            cursor = page["nextCursor"]
            if cursor is None:
                break
        version = _version(self.source_id, rows)
        yield DataBatch(
            BatchKind.ARROW,
            rows,
            (version,),
            tuple(LineageRef(self.source_id, self.asset_id, row["appointment_id"]) for row in rows),
            row_count=len(rows),
        )
