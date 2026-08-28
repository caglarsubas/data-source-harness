"""Execute the real harness gateway against the internal Phase 7 source lab."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from data_source_harness.connector import Capability, ConnectorRegistry, UnsupportedCapability
from data_source_harness.decoder import DecodeRequest, DecoderRegistry, PayloadFormat
from data_source_harness.models import DataBatch, LineageRef, QueryRequest
from data_source_harness.planning import BoundedQueryPlanner, PlanningConstraints, QueryIntent
from data_source_harness.policy import AuthorizationRequest, PolicyDecision, RequestIdentity
from data_source_harness.runtime import HarnessGateway
from data_source_harness.telemetry import MemoryTelemetrySink
from reference_labs.white_goods.lab import WhiteGoodsLab
from reference_labs.white_goods.live.connectors import (
    KafkaLiveConnector,
    PostgreSQLLiveConnector,
    RestLiveConnector,
    S3LiveConnector,
)


class LocalReadPolicy:
    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        allowed = (
            request.identity.organization_id == "org-lab"
            and request.identity.solution_id == "whitegoods-lab"
            and request.capability in {Capability.DISCOVER, Capability.QUERY}
            and request.source_id.startswith("whitegoods.")
        )
        return PolicyDecision(
            allowed,
            f"phase7-local:{request.identity.request_id}:{request.capability.value}",
            "local_read_allowed" if allowed else "local_scope_denied",
        )


def _identity() -> RequestIdentity:
    return RequestIdentity(
        "org-lab",
        "whitegoods-lab",
        "agent.phase7-acceptance",
        "phase7-live-harness",
        "trace.phase7-live-harness",
        "policy:phase7-local-read-v1",
    )


async def _collect(stream: AsyncIterator[DataBatch]) -> tuple[DataBatch, ...]:
    return tuple([batch async for batch in stream])


async def run_probe() -> dict[str, Any]:
    connectors = (
        PostgreSQLLiveConnector(
            host="postgresql",
            database="whitegoods",
            user_file="/run/secrets/postgres-user",
            password_file="/run/secrets/postgres-password",
        ),
        S3LiveConnector(
            endpoint="http://object-store:9000",
            access_key_file="/run/secrets/object-store-user",
            secret_key_file="/run/secrets/object-store-password",
        ),
        KafkaLiveConnector(bootstrap_servers="event-stream:9092"),
        RestLiveConnector(
            base_url="http://service-api:8080/v1",
            credential_file="/run/secrets/service-api-credential",
        ),
    )
    registry = ConnectorRegistry()
    for connector in connectors:
        registry.register(connector)
    telemetry = MemoryTelemetrySink()
    gateway = HarnessGateway(registry, LocalReadPolicy(), telemetry)
    identity = _identity()
    checks: list[dict[str, Any]] = []

    health = [await connector.health() for connector in connectors]
    checks.append(
        {
            "checkId": "runtime.connectors-healthy",
            "passed": all(item.healthy for item in health),
            "observed": len(health),
        }
    )

    discovered = {
        connector.profile.connector_id: await gateway.discover(
            connector.profile.connector_id, identity
        )
        for connector in connectors
    }
    checks.append(
        {
            "checkId": "harness.discovery-four-shapes",
            "passed": set(discovered)
            == {
                "whitegoods.erp",
                "whitegoods.documents",
                "whitegoods.telemetry",
                "whitegoods.service-api",
            }
            and all(discovered.values()),
            "observed": sum(len(items) for items in discovered.values()),
        }
    )

    plan = BoundedQueryPlanner().compile(
        QueryIntent(
            "whitegoods.erp",
            ("service_orders",),
            {
                "service_orders": (
                    "service_order_id",
                    "serial_number",
                    "error_code",
                    "symptom",
                    "resolution",
                )
            },
            {"service_orders": {"error_code": "E21"}},
            (),
            2,
            5_000,
            "repeat service diagnosis",
        ),
        PlanningConstraints(
            {
                "service_orders": frozenset(
                    {
                        "service_order_id",
                        "serial_number",
                        "error_code",
                        "symptom",
                        "resolution",
                    }
                )
            },
            frozenset(),
            1,
            5,
            5_000,
        ),
    )
    postgres_batches = await _collect(gateway.execute(plan.to_query_request(), identity))
    postgres_rows = postgres_batches[0].payload
    checks.append(
        {
            "checkId": "harness.bounded-postgresql-query",
            "passed": len(postgres_rows) == 2
            and all(row["error_code"] == "E21" for row in postgres_rows),
            "observed": len(postgres_rows),
        }
    )

    document_request = QueryRequest(
        "whitegoods.documents",
        ("technical-documents",),
        {},
        4,
        5_000,
        "technical guidance discovery",
    )
    document_batches = await _collect(gateway.execute(document_request, identity))
    document_rows = document_batches[0].payload
    document_key = next(
        row["key"] for row in document_rows if row["key"].endswith("washing-machine-e21-manual.md")
    )
    s3_connector = connectors[1]
    payload = s3_connector.read_object(document_key)
    decoded = (
        await DecoderRegistry.with_standard_decoders()
        .get(PayloadFormat.TEXT)
        .decode(
            DecodeRequest(
                payload,
                PayloadFormat.TEXT,
                document_batches[0].source_versions[0],
                (LineageRef("whitegoods.documents", "technical-documents", document_key),),
                "text/markdown",
            )
        )
    )
    checks.append(
        {
            "checkId": "harness.s3-decode-untrusted",
            "passed": len(document_rows) == 4
            and decoded.trust.value == "untrusted-source"
            and bool(decoded.batches[0].lineage),
            "observed": len(payload),
        }
    )

    telemetry_batches = await _collect(
        gateway.execute(
            QueryRequest(
                "whitegoods.telemetry",
                ("telemetry",),
                {},
                9,
                7_000,
                "fault telemetry snapshot",
            ),
            identity,
        )
    )
    events = telemetry_batches[0].payload
    checks.append(
        {
            "checkId": "harness.kafka-bounded-snapshot",
            "passed": len(events) == 9 and events[0]["event_id"] == "EV001",
            "observed": len(events),
        }
    )

    appointment_batches = await _collect(
        gateway.execute(
            QueryRequest(
                "whitegoods.service-api",
                ("appointments",),
                {},
                3,
                5_000,
                "appointment context",
            ),
            identity,
        )
    )
    appointments = appointment_batches[0].payload
    checks.append(
        {
            "checkId": "harness.rest-auth-pagination",
            "passed": len(appointments) == 3
            and len({row["appointment_id"] for row in appointments}) == 3,
            "observed": len(appointments),
        }
    )

    batches = (*postgres_batches, *document_batches, *telemetry_batches, *appointment_batches)
    checks.append(
        {
            "checkId": "harness.exact-provenance",
            "passed": all(batch.lineage and batch.source_versions for batch in batches)
            and {batch.source_versions[0].source_id for batch in batches}
            == {
                "whitegoods.erp",
                "whitegoods.documents",
                "whitegoods.telemetry",
                "whitegoods.service-api",
            },
            "observed": sum(len(batch.lineage) for batch in batches),
        }
    )

    aliases = WhiteGoodsLab.semantic_graph().equivalence_cluster("term:drainage-motor")
    checks.append(
        {
            "checkId": "harness.semantic-resolution",
            "passed": aliases == frozenset({"part:drain-pump", "term:drainage-motor"}),
            "observed": len(aliases),
        }
    )

    action_denied = False
    try:
        registry.get("whitegoods.service-api", Capability.MUTATE)
    except UnsupportedCapability:
        action_denied = True
    checks.append(
        {
            "checkId": "governance.read-only-action-denied",
            "passed": action_denied,
            "observed": 1 if action_denied else 0,
        }
    )
    checks.append(
        {
            "checkId": "runtime.gateway-telemetry",
            "passed": len(telemetry.events) >= 12
            and all(entry.identity.solution_id == "whitegoods-lab" for entry in telemetry.events),
            "observed": len(telemetry.events),
        }
    )

    return {
        "schemaVersion": "data.harness.local-harness-runtime-evidence/v1",
        "campaignId": "phase7-white-goods-local-harness-runtime",
        "generatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "revision": os.environ["HARNESS_SOURCE_REVISION"],
        "artifactDigest": os.environ["HARNESS_ARTIFACT_DIGEST"],
        "harnessVersion": os.environ["HARNESS_VERSION"],
        "networkMode": "compose-internal",
        "externalResourcesCreated": [],
        "sourceRecordCounts": {
            "whitegoods.postgresql": len(postgres_rows),
            "whitegoods.object-store": len(document_rows),
            "whitegoods.event-stream": len(events),
            "whitegoods.service-api": len(appointments),
        },
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
    }


def main() -> int:
    report = asyncio.run(run_probe())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
