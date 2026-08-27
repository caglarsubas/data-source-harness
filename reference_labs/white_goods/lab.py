"""Deterministic offline runtime for the white-goods reference lab."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_source_harness.connector import (
    Capability,
    ConnectorLimits,
    ConnectorProfile,
    ConnectorRegistry,
    DataModel,
    HealthStatus,
    RuntimeMode,
    UnsupportedCapability,
)
from data_source_harness.coordination import (
    CrossSourceCoordinator,
    QueryStep,
    SearchStep,
    SourceExecutionPlan,
)
from data_source_harness.coverage import CoverageStatement
from data_source_harness.decoder import (
    ContentTrust,
    DecodeRequest,
    DecodeResult,
    DecoderRegistry,
    PayloadFormat,
)
from data_source_harness.models import (
    Asset,
    AssetRef,
    AssetSchema,
    BatchKind,
    ChangeEvent,
    DataBatch,
    FieldSchema,
    LineageRef,
    QueryRequest,
    SearchHit,
    SearchRequest,
    SourceVersion,
)
from data_source_harness.policy import (
    AuthorizationRequest,
    PolicyDecision,
    RequestIdentity,
)
from data_source_harness.runtime import HarnessGateway
from data_source_harness.semantic import AssertionGraph, AssertionPredicate, SemanticAssertion
from data_source_harness.telemetry import MemoryTelemetrySink

LAB_ROOT = Path(__file__).resolve().parent
DATA_ROOT = LAB_ROOT / "data"
FIXED_TIME = datetime(2026, 8, 27, tzinfo=UTC)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class LabSourceUnavailable(RuntimeError):
    pass


def _digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(LAB_ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def dataset_digest() -> str:
    return _digest([path for path in DATA_ROOT.rglob("*") if path.is_file()])


def _tokens(value: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(value.lower()))


@dataclass(frozen=True)
class LabDocument:
    document_id: str
    product: str
    acl_roles: frozenset[str]
    title: str
    content: str
    content_hash: str
    trust: str = "untrusted-source"


class MarkdownLabDecoder:
    decoder_id = "whitegoods.markdown/v1"
    supported_formats = frozenset({PayloadFormat.TEXT})

    async def decode(self, request: DecodeRequest) -> DecodeResult:
        if request.media_type not in {"text/markdown", "text/plain"}:
            raise ValueError(f"unsupported media type: {request.media_type}")
        content = request.payload.decode("utf-8")
        batch = DataBatch(
            BatchKind.DOCUMENT,
            {"content": content, "media_type": request.media_type},
            (request.source_version,),
            request.lineage,
            row_count=1,
            byte_count=len(request.payload),
        )
        return DecodeResult((batch,), ContentTrust.UNTRUSTED_SOURCE)


class BaseLabConnector:
    def __init__(
        self, profile: ConnectorProfile, asset_schemas: Mapping[str, tuple[FieldSchema, ...]]
    ):
        self._profile = profile
        self._asset_schemas = dict(asset_schemas)
        self.available = True
        self.version = SourceVersion(profile.connector_id, f"sha256:{dataset_digest()}", FIXED_TIME)

    @property
    def profile(self) -> ConnectorProfile:
        return self._profile

    async def health(self) -> HealthStatus:
        limitations = () if self.available else ("injected_source_outage",)
        return HealthStatus(self.available, self.profile.version, limitations)

    def _require_available(self) -> None:
        if not self.available:
            raise LabSourceUnavailable(f"injected outage: {self.profile.connector_id}")

    async def discover(self, cursor: str | None = None) -> tuple[Asset, ...]:
        self._require_available()
        return tuple(
            Asset(
                AssetRef(self.profile.connector_id, asset_id),
                asset_id,
                "mock-asset",
                metadata={"dataset_version": self.version.version},
            )
            for asset_id in sorted(self._asset_schemas)
        )

    async def describe(self, asset: AssetRef) -> AssetSchema:
        self._require_available()
        if (
            asset.source_id != self.profile.connector_id
            or asset.asset_id not in self._asset_schemas
        ):
            raise KeyError(f"unknown asset: {asset}")
        return AssetSchema(asset, self._asset_schemas[asset.asset_id], self.version)

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        raise UnsupportedCapability(self.profile.connector_id, Capability.SEARCH)

    async def subscribe(self, checkpoint: str | None = None) -> AsyncIterator[ChangeEvent]:
        raise UnsupportedCapability(self.profile.connector_id, Capability.SUBSCRIBE)
        if False:  # pragma: no cover
            yield

    async def mutate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        raise UnsupportedCapability(self.profile.connector_id, Capability.MUTATE)

    async def checkpoint(self, stream_id: str) -> str:
        raise UnsupportedCapability(self.profile.connector_id, Capability.SUBSCRIBE)

    async def explain(self, request: QueryRequest) -> Mapping[str, Any]:
        return {"source": self.profile.connector_id, "bounded": True, "plan": dict(request.plan)}


class StructuredConnector(BaseLabConnector):
    FILES = {
        "products": DATA_ROOT / "master/products.csv",
        "customers": DATA_ROOT / "master/customers.csv",
        "installed_products": DATA_ROOT / "master/installed_products.csv",
        "service_orders": DATA_ROOT / "service/service_orders.csv",
        "quality_inspections": DATA_ROOT / "quality/quality_inspections.csv",
    }
    PRIMARY_KEYS = {
        "products": "product_id",
        "customers": "customer_id",
        "installed_products": "serial_number",
        "service_orders": "service_order_id",
        "quality_inspections": "inspection_id",
    }

    def __init__(self) -> None:
        schemas = {
            asset: tuple(FieldSchema(name, "string") for name in self._read_csv(path)[0])
            for asset, path in self.FILES.items()
        }
        super().__init__(
            ConnectorProfile(
                "whitegoods.erp",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.TABULAR}),
                frozenset(
                    {
                        Capability.DISCOVER,
                        Capability.DESCRIBE,
                        Capability.QUERY,
                        Capability.PREDICATE_PUSHDOWN,
                        Capability.PROJECTION_PUSHDOWN,
                    }
                ),
                frozenset({"credential_reference"}),
                limits=ConnectorLimits(max_parallelism=4, max_result_bytes=5_000_000),
            ),
            schemas,
        )
        self.rows: dict[str, list[dict[str, str]]] = {}
        self.reset()

    @staticmethod
    def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = [dict(row) for row in reader]
            return list(reader.fieldnames or []), rows

    def reset(self) -> None:
        self.rows = {asset: self._read_csv(path)[1] for asset, path in self.FILES.items()}
        self.available = True

    def snapshot_digest(self) -> str:
        payload = json.dumps(self.rows, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._require_available()
        select_by_asset = request.plan.get("select_by_asset")
        where_by_asset = request.plan.get("where_by_asset")
        canonical = select_by_asset is not None or where_by_asset is not None
        if canonical and (
            not isinstance(select_by_asset, Mapping) or not isinstance(where_by_asset, Mapping)
        ):
            raise ValueError("canonical select and filter scopes must be mappings")
        for asset in request.asset_ids:
            if asset not in self.rows:
                raise KeyError(f"unknown structured asset: {asset}")
            where = where_by_asset.get(asset, {}) if canonical else request.plan.get("where", {})
            select = tuple(
                select_by_asset.get(asset, ()) if canonical else request.plan.get("select", ())
            )
            if not isinstance(where, Mapping):
                raise ValueError("where must be a mapping")
            allowed_fields = {field.name for field in self._asset_schemas[asset]}
            if not set(where).issubset(allowed_fields) or not set(select).issubset(allowed_fields):
                raise ValueError("query references an unknown field")
            matched = [
                row
                for row in self.rows[asset]
                if all(str(row.get(key)) == str(value) for key, value in where.items())
            ][: request.limit]
            payload = [
                ({key: row[key] for key in select} if select else dict(row)) for row in matched
            ]
            primary_key = self.PRIMARY_KEYS[asset]
            lineage = tuple(
                LineageRef(self.profile.connector_id, asset, row[primary_key]) for row in matched
            ) or (LineageRef(self.profile.connector_id, asset, "empty-result"),)
            yield DataBatch(
                BatchKind.ARROW, payload, (self.version,), lineage, row_count=len(payload)
            )


def _parse_documents() -> tuple[LabDocument, ...]:
    documents: list[LabDocument] = []
    for path in sorted((DATA_ROOT / "documents").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        _, frontmatter, content = text.split("---", 2)
        metadata = {
            key.strip(): value.strip()
            for line in frontmatter.strip().splitlines()
            for key, value in [line.split(":", 1)]
        }
        title = next(
            (
                line.removeprefix("# ").strip()
                for line in content.splitlines()
                if line.startswith("# ")
            ),
            path.stem,
        )
        documents.append(
            LabDocument(
                metadata["document_id"],
                metadata["product"],
                frozenset(item.strip() for item in metadata["acl"].split(",")),
                title,
                content.strip(),
                hashlib.sha256(text.encode()).hexdigest(),
            )
        )
    return tuple(documents)


class DocumentConnector(BaseLabConnector):
    def __init__(self) -> None:
        super().__init__(
            ConnectorProfile(
                "whitegoods.documents",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.DOCUMENT}),
                frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
                frozenset({"credential_reference"}),
            ),
            {
                "technical_documents": (
                    FieldSchema("document_id", "string", False),
                    FieldSchema("product", "string", False),
                    FieldSchema("content", "string", False),
                    FieldSchema("acl_roles", "array", False),
                    FieldSchema("trust", "string", False),
                )
            },
        )
        self.documents = _parse_documents()

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._require_available()
        role = str(request.plan.get("role", ""))
        product = request.plan.get("product")
        visible = [
            document
            for document in self.documents
            if role in document.acl_roles and (product is None or product == document.product)
        ][: request.limit]
        payload = [
            {
                "document_id": item.document_id,
                "product": item.product,
                "title": item.title,
                "content": item.content,
                "acl_roles": sorted(item.acl_roles),
                "content_hash": item.content_hash,
                "trust": item.trust,
            }
            for item in visible
        ]
        lineage = tuple(
            LineageRef(self.profile.connector_id, "technical_documents", item.document_id)
            for item in visible
        ) or (LineageRef(self.profile.connector_id, "technical_documents", "empty-result"),)
        yield DataBatch(
            BatchKind.DOCUMENT, payload, (self.version,), lineage, row_count=len(payload)
        )


class SearchConnector(BaseLabConnector):
    SYNONYMS = {
        "drainage": {"drain", "pump"},
        "motor": {"pump"},
        "e21": {"drain", "pump", "filter", "hose"},
        "e05": {"temperature", "sensor", "airflow"},
        "repeat": {"revision", "lot", "visits"},
    }

    def __init__(self, documents: tuple[LabDocument, ...]) -> None:
        self.documents = documents
        super().__init__(
            ConnectorProfile(
                "whitegoods.search",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.VECTOR, DataModel.DOCUMENT}),
                frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.SEARCH}),
                frozenset({"credential_reference"}),
            ),
            {
                "technical_document_index": (
                    FieldSchema("document_id", "string", False),
                    FieldSchema("content", "text", False),
                    FieldSchema("acl_roles", "array", False),
                )
            },
        )

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        raise UnsupportedCapability(self.profile.connector_id, Capability.QUERY)
        if False:  # pragma: no cover
            yield

    async def search(self, request: SearchRequest) -> tuple[SearchHit, ...]:
        self._require_available()
        role = str(request.filters.get("role", ""))
        product = request.filters.get("product")
        query_tokens = _tokens(request.query)
        expanded = set(query_tokens)
        for token in query_tokens:
            expanded.update(self.SYNONYMS.get(token, set()))
        ranked: list[tuple[float, LabDocument]] = []
        for document in self.documents:
            if role not in document.acl_roles or (
                product is not None and product != document.product
            ):
                continue
            document_tokens = _tokens(f"{document.title} {document.content}")
            lexical = len(query_tokens & document_tokens) / max(1, len(query_tokens))
            semantic = len(expanded & document_tokens) / max(1, len(expanded))
            score = 0.6 * lexical + 0.4 * semantic
            if score > 0:
                ranked.append((score, document))
        ranked.sort(key=lambda item: (-item[0], item[1].document_id))
        return tuple(
            SearchHit(
                self.profile.connector_id,
                "technical_document_index",
                document.document_id,
                score,
                self.version,
                (LineageRef("whitegoods.documents", "technical_documents", document.document_id),),
                lexical_score=score,
                dense_score=score,
                acl_decision_id=f"lab-role:{role}",
            )
            for score, document in ranked[: request.top_k]
        )


class EventConnector(BaseLabConnector):
    def __init__(self) -> None:
        super().__init__(
            ConnectorProfile(
                "whitegoods.telemetry",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.EVENT}),
                frozenset(
                    {
                        Capability.DISCOVER,
                        Capability.DESCRIBE,
                        Capability.QUERY,
                        Capability.SUBSCRIBE,
                        Capability.CDC,
                    }
                ),
                frozenset({"credential_reference"}),
                consistency=self._consistency(),
            ),
            {
                "telemetry_events": (
                    FieldSchema("sequence", "integer", False),
                    FieldSchema("event_id", "string", False),
                    FieldSchema("event_time", "timestamp", False),
                    FieldSchema("observed_at", "timestamp", False),
                    FieldSchema("serial_number", "string"),
                    FieldSchema("event_type", "string", False),
                )
            },
        )
        self.raw_events = tuple(
            json.loads(line)
            for line in (DATA_ROOT / "events/telemetry.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )

    @staticmethod
    def _consistency():
        from data_source_harness.connector import ConsistencyProfile

        return ConsistencyProfile(
            read_isolation=("eventual",),
            change_delivery="at-least-once-with-deduplication-key",
            supports_checkpoint=True,
            supports_cdc=True,
        )

    def logical_events(self) -> tuple[dict[str, Any], ...]:
        seen: set[str] = set()
        events: list[dict[str, Any]] = []
        for event in sorted(self.raw_events, key=lambda item: item["sequence"]):
            if event["event_id"] in seen or not event.get("serial_number"):
                continue
            seen.add(event["event_id"])
            events.append(dict(event))
        return tuple(events)

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._require_available()
        events = self.logical_events()[: request.limit]
        lineage = tuple(
            LineageRef(self.profile.connector_id, "telemetry_events", event["event_id"])
            for event in events
        )
        yield DataBatch(BatchKind.EVENT, events, (self.version,), lineage, row_count=len(events))

    async def subscribe(self, checkpoint: str | None = None) -> AsyncIterator[ChangeEvent]:
        self._require_available()
        position = int(checkpoint or 0)
        for event in self.logical_events():
            if int(event["sequence"]) <= position:
                continue
            yield ChangeEvent(
                event["event_id"],
                self.profile.connector_id,
                "telemetry_events",
                "upsert",
                datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00")),
                event,
                str(event["sequence"]),
            )

    async def checkpoint(self, stream_id: str) -> str:
        if stream_id != "telemetry_events":
            raise KeyError(stream_id)
        return str(max(event["sequence"] for event in self.raw_events))


class ServiceApiConnector(BaseLabConnector):
    def __init__(self) -> None:
        super().__init__(
            ConnectorProfile(
                "whitegoods.service-api",
                "1.0.0",
                "harness.connector/v1",
                RuntimeMode.PROCESS,
                frozenset({DataModel.TABULAR}),
                frozenset({Capability.DISCOVER, Capability.DESCRIBE, Capability.QUERY}),
                frozenset({"oauth2_credential_reference"}),
            ),
            {
                "appointments": (
                    FieldSchema("appointment_id", "string", False),
                    FieldSchema("service_order_id", "string", False),
                    FieldSchema("technician_id", "string", False),
                    FieldSchema("scheduled_at", "timestamp", False),
                    FieldSchema("status", "string", False),
                )
            },
        )
        self.fixture = json.loads(
            (DATA_ROOT / "api/service-api-fixtures.json").read_text(encoding="utf-8")
        )

    async def execute(self, request: QueryRequest) -> AsyncIterator[DataBatch]:
        self._require_available()
        service_order_id = request.plan.get("service_order_id")
        rows = [
            row
            for row in self.fixture["appointments"]
            if service_order_id is None or row["service_order_id"] == service_order_id
        ][: request.limit]
        page_size = min(int(request.plan.get("page_size", 2)), request.limit)
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        cursor = int(request.plan.get("cursor", 0))
        for page_start in range(cursor, len(rows), page_size):
            page = rows[page_start : page_start + page_size]
            lineage = tuple(
                LineageRef(self.profile.connector_id, "appointments", row["appointment_id"])
                for row in page
            )
            yield DataBatch(BatchKind.ARROW, page, (self.version,), lineage, row_count=len(page))
        if not rows:
            yield DataBatch(
                BatchKind.ARROW,
                [],
                (self.version,),
                (LineageRef(self.profile.connector_id, "appointments", "empty-result"),),
                row_count=0,
            )


class WhiteGoodsPolicy:
    ROLES = {
        "agent-service-c001": {"role": "service", "customers": {"C001"}},
        "agent-service-c002": {"role": "service", "customers": {"C002"}},
        "agent-quality": {"role": "quality", "customers": set()},
    }

    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        grant = self.ROLES.get(request.identity.agent_id)
        reason = "allowlisted"
        allowed = grant is not None
        if allowed and request.capability not in {
            Capability.DISCOVER,
            Capability.QUERY,
            Capability.SEARCH,
        }:
            allowed, reason = False, "capability_not_allowed"
        requested_role = request.attributes.get("role")
        parameter_role = request.parameters.get("role")
        if (
            allowed
            and requested_role != parameter_role
            and (requested_role is not None or parameter_role is not None)
        ):
            allowed, reason = False, "scope_attribute_mismatch"
        if allowed and requested_role is not None and requested_role != grant["role"]:
            allowed, reason = False, "role_mismatch"
        customer_id = request.attributes.get("customer_id")
        where = request.parameters.get("where", {})
        planned_customer = where.get("customer_id") if isinstance(where, Mapping) else None
        if (
            allowed
            and customer_id != planned_customer
            and (customer_id is not None or planned_customer is not None)
        ):
            allowed, reason = False, "scope_attribute_mismatch"
        if allowed and customer_id is not None:
            customers = grant["customers"]
            if customer_id not in customers:
                allowed, reason = False, "customer_scope_denied"
        if not allowed and reason == "allowlisted":
            reason = "unknown_agent"
        decision_id = f"whitegoods:{request.identity.request_id}:{reason}"
        return PolicyDecision(allowed, decision_id, reason)


class WhiteGoodsLab:
    def __init__(self) -> None:
        self.erp = StructuredConnector()
        self.documents = DocumentConnector()
        self.search = SearchConnector(self.documents.documents)
        self.events = EventConnector()
        self.service_api = ServiceApiConnector()
        self.connectors = (
            self.erp,
            self.documents,
            self.events,
            self.service_api,
            self.search,
        )
        self.registry = ConnectorRegistry()
        for connector in self.connectors:
            self.registry.register(connector)
        self.telemetry = MemoryTelemetrySink()
        self.gateway = HarnessGateway(self.registry, WhiteGoodsPolicy(), self.telemetry)
        self.decoder_registry = DecoderRegistry()
        self.decoder_registry.register(MarkdownLabDecoder())

    def reset(self) -> None:
        self.erp.reset()
        for connector in self.connectors:
            connector.available = True
        self.telemetry.events.clear()

    @staticmethod
    def identity(agent_id: str, request_id: str = "lab-request") -> RequestIdentity:
        return RequestIdentity(
            "whitegoods-lab",
            "service-quality",
            agent_id,
            request_id,
            f"trace:{request_id}",
            "sha256:whitegoods-policy-v1",
        )

    @staticmethod
    def semantic_graph() -> AssertionGraph:
        graph = AssertionGraph()
        graph.append(
            SemanticAssertion(
                "wg-a1",
                "term:drainage-motor",
                AssertionPredicate.SAME_AS,
                "part:drain-pump",
                1.0,
                FIXED_TIME,
                FIXED_TIME,
                None,
                "sha256:whitegoods-policy-v1",
                (LineageRef("whitegoods.documents", "technical_documents", "DOC-WM-E21"),),
            )
        )
        graph.append(
            SemanticAssertion(
                "wg-a2",
                "error:E21",
                AssertionPredicate.MENTIONS,
                "part:drain-pump",
                0.95,
                FIXED_TIME,
                FIXED_TIME,
                None,
                "sha256:whitegoods-policy-v1",
                (LineageRef("whitegoods.documents", "technical_documents", "DOC-WM-E21"),),
            )
        )
        return graph

    async def repeat_visit_model(self) -> str:
        identity = self.identity("agent-quality", "repeat-visits")
        request = QueryRequest(
            "whitegoods.erp",
            ("service_orders",),
            {},
            100,
            1_000,
            "aggregate repeat service analysis",
        )
        batches = [batch async for batch in self.gateway.execute(request, identity)]
        visits: dict[str, int] = {}
        for row in batches[0].payload:
            visits[row["serial_number"]] = max(
                visits.get(row["serial_number"], 0), int(row["visit_number"])
            )
        repeat_serials = {serial for serial, count in visits.items() if count > 1}
        installed = {
            row["serial_number"]: row["product_id"] for row in self.erp.rows["installed_products"]
        }
        products = {row["product_id"]: row["model_code"] for row in self.erp.rows["products"]}
        counts: dict[str, int] = {}
        for serial in repeat_serials:
            model = products[installed[serial]]
            counts[model] = counts.get(model, 0) + 1
        return max(counts, key=counts.get)

    async def e21_cross_source_brief(self) -> tuple[dict[str, Any], CoverageStatement]:
        identity = self.identity("agent-quality", "e21-cross-source")
        service_request = QueryRequest(
            "whitegoods.erp",
            ("service_orders",),
            {"where": {"error_code": "E21"}},
            20,
            1_000,
            "E21 quality and service analysis",
        )
        event_request = QueryRequest(
            "whitegoods.telemetry",
            ("telemetry_events",),
            {},
            100,
            1_000,
            "E21 telemetry correlation",
        )
        search_request = SearchRequest(
            "whitegoods.search",
            "repeat E21 drain pump filter hose quality lot",
            3,
            {"role": "quality"},
            "E21 guided diagnosis",
            {"role": "quality"},
        )
        appointment_request = QueryRequest(
            "whitegoods.service-api",
            ("appointments",),
            {"service_order_id": "SO1002", "page_size": 2},
            10,
            1_000,
            "E21 appointment evidence",
        )
        result = await CrossSourceCoordinator(self.gateway).execute(
            SourceExecutionPlan(
                "e21-cross-source",
                FIXED_TIME,
                (
                    QueryStep("service", service_request),
                    QueryStep("telemetry", event_request),
                    QueryStep("appointments", appointment_request),
                ),
                (
                    SearchStep(
                        "guidance",
                        search_request,
                        ("technical_document_index",),
                    ),
                ),
            ),
            identity,
        )
        service_batches = list(result.step("service").batches)
        event_batches = list(result.step("telemetry").batches)
        hits = result.step("guidance").hits
        appointment_batches = list(result.step("appointments").batches)
        service_rows = service_batches[0].payload
        events = [event for event in event_batches[0].payload if event.get("error_code") == "E21"]
        appointments = [row for batch in appointment_batches for row in batch.payload]
        lineage_count = sum(
            len(batch.lineage) for batch in service_batches + event_batches + appointment_batches
        ) + sum(len(hit.lineage) for hit in hits)
        brief = {
            "service_order_ids": [row["service_order_id"] for row in service_rows],
            "telemetry_event_ids": [event["event_id"] for event in events],
            "document_ids": [hit.record_id for hit in hits],
            "appointment_ids": [row["appointment_id"] for row in appointments],
            "lineage_count": lineage_count,
        }
        return brief, result.coverage
