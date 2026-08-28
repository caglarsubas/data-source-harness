"""Execute the real harness gateway against the internal Phase 7 source lab."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from data_source_harness.actions import (
    ActionExecutionFailed,
    ActionGateway,
    ActionRisk,
    ActionState,
    ApprovalMode,
    ApprovalRequired,
    CompensationSpec,
    HmacApprovalAuthority,
    SourceActionPlan,
)
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


class LocalMutationPolicy:
    """Allow only the representative, supervised service-order operations."""

    async def evaluate(self, request: AuthorizationRequest) -> PolicyDecision:
        operation = str(request.parameters.get("operation", ""))
        allowed = (
            request.identity.organization_id == "org-lab"
            and request.identity.solution_id == "whitegoods-lab"
            and request.identity.agent_id == "agent.phase7-acceptance"
            and request.source_id == "whitegoods.erp"
            and request.capability is Capability.MUTATE
            and request.asset_ids == ("service_orders",)
            and operation in {"resolve-service-order", "restore-service-order"}
        )
        return PolicyDecision(
            allowed,
            f"phase7-mutation:{request.identity.request_id}:{request.attributes['stage']}",
            "local_mutation_allowed" if allowed else "local_mutation_denied",
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


def _mutation_identity() -> RequestIdentity:
    return RequestIdentity(
        "org-lab",
        "whitegoods-lab",
        "agent.phase7-acceptance",
        "phase7-live-mutation",
        "trace.phase7-live-mutation",
        "policy:phase7-local-mutation-v1",
    )


async def _collect(stream: AsyncIterator[DataBatch]) -> tuple[DataBatch, ...]:
    return tuple([batch async for batch in stream])


async def _exercise_mutation(
    connector: PostgreSQLLiveConnector,
) -> list[dict[str, Any]]:
    """Run the real preview/approval/idempotency/compensation lifecycle."""

    observed_at = datetime.now(UTC)
    identity = _mutation_identity()
    authority = HmacApprovalAuthority(
        "adlc-phase7-local",
        "data-source-harness",
        b"phase7-local-disposable-approval-key",
    )
    telemetry = MemoryTelemetrySink()
    registry = ConnectorRegistry()
    registry.register(connector)

    def new_gateway() -> ActionGateway:
        return ActionGateway(
            registry,
            LocalMutationPolicy(),
            telemetry,
            now=lambda: observed_at,
            approval_verifier=authority,
        )

    action = SourceActionPlan(
        "phase7-resolve-SO1001",
        "whitegoods.erp",
        "service_orders",
        "resolve-service-order",
        {
            "serviceOrderId": "SO1001",
            "resolution": "replaced drain pump and verified flow",
        },
        {"recordVersion": 1, "expectedResolution": "replaced drain pump"},
        "phase7:SO1001:resolve:v1",
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "verify supervised service-order resolution",
        CompensationSpec(
            "restore-service-order",
            {"serviceOrderId": "SO1001", "resolution": "replaced drain pump"},
            {
                "recordVersion": 2,
                "expectedResolution": "replaced drain pump and verified flow",
            },
        ),
    )
    approval = authority.issue(
        action_digest=action.digest,
        approver_id="human:phase7-lab-supervisor",
        policy_digest=identity.policy_digest,
        approved_at=observed_at - timedelta(minutes=1),
        expires_at=observed_at + timedelta(minutes=10),
        allow_compensation=True,
        identity=identity,
        nonce="SO1001-resolution-v1",
    )
    gateway = new_gateway()
    preview = await gateway.preview(action, identity)
    approval_required = False
    try:
        await gateway.execute(action, preview, identity)
    except ApprovalRequired:
        approval_required = True

    receipt = await gateway.execute(action, preview, identity, approval)
    gateway_replay = await gateway.execute(action, preview, identity, approval)
    changed = connector.read_mutation_state("SO1001")

    restarted_gateway = new_gateway()
    restarted_preview = await restarted_gateway.preview(action, identity)
    source_replay = await restarted_gateway.execute(
        action, restarted_preview, identity, approval
    )
    replayed = connector.read_mutation_state("SO1001")

    stale = SourceActionPlan(
        "phase7-stale-SO1001",
        "whitegoods.erp",
        "service_orders",
        "resolve-service-order",
        {"serviceOrderId": "SO1001", "resolution": "unsafe stale overwrite"},
        {"recordVersion": 1, "expectedResolution": "replaced drain pump"},
        "phase7:SO1001:stale:v1",
        ActionRisk.HIGH,
        ApprovalMode.HUMAN,
        "prove optimistic-concurrency denial",
    )
    stale_approval = authority.issue(
        action_digest=stale.digest,
        approver_id="human:phase7-lab-supervisor",
        policy_digest=identity.policy_digest,
        approved_at=observed_at - timedelta(minutes=1),
        expires_at=observed_at + timedelta(minutes=10),
        allow_compensation=False,
        identity=identity,
        nonce="SO1001-stale-v1",
    )
    stale_denied = False
    stale_preview = await restarted_gateway.preview(stale, identity)
    try:
        await restarted_gateway.execute(stale, stale_preview, identity, stale_approval)
    except ActionExecutionFailed:
        stale_denied = True
    after_stale = connector.read_mutation_state("SO1001")

    compensated = await gateway.compensate(action, receipt, identity, approval)
    restored = connector.read_mutation_state("SO1001")
    sensitive = {
        "replaced drain pump",
        "replaced drain pump and verified flow",
        "unsafe stale overwrite",
    }
    audit_payload_free = all(
        not any(value in json.dumps(dict(entry.attributes)) for value in sensitive)
        for entry in (*gateway.audit.entries, *restarted_gateway.audit.entries)
    )
    telemetry_payload_free = all(
        not any(value in json.dumps(dict(event.attributes)) for value in sensitive)
        for event in telemetry.events
    )
    checks = [
        {
            "checkId": "mutation.preview-policy-bound",
            "passed": preview.allowed and preview.approval_required,
            "observed": 1,
        },
        {
            "checkId": "mutation.human-approval-required",
            "passed": approval_required,
            "observed": 1 if approval_required else 0,
        },
        {
            "checkId": "mutation.postgresql-executed",
            "passed": receipt.state is ActionState.EXECUTED
            and changed["recordVersion"] == 2,
            "observed": changed["recordVersion"],
        },
        {
            "checkId": "mutation.gateway-replay-idempotent",
            "passed": gateway_replay.state is ActionState.ALREADY_EXECUTED
            and changed["idempotencyRecords"] == 1,
            "observed": changed["idempotencyRecords"],
        },
        {
            "checkId": "mutation.source-replay-after-gateway-restart",
            "passed": source_replay.state is ActionState.EXECUTED
            and replayed["recordVersion"] == 2
            and replayed["idempotencyRecords"] == 1,
            "observed": replayed["recordVersion"],
        },
        {
            "checkId": "mutation.stale-precondition-denied",
            "passed": stale_denied and after_stale == replayed,
            "observed": 1 if stale_denied else 0,
        },
        {
            "checkId": "mutation.compensated",
            "passed": compensated.state is ActionState.COMPENSATED
            and restored["resolution"] == "replaced drain pump"
            and restored["recordVersion"] == 3
            and restored["idempotencyRecords"] == 2,
            "observed": restored["recordVersion"],
        },
        {
            "checkId": "mutation.audit-chain-payload-free",
            "passed": gateway.audit.verify()
            and restarted_gateway.audit.verify()
            and audit_payload_free,
            "observed": len(gateway.audit.entries) + len(restarted_gateway.audit.entries),
        },
        {
            "checkId": "mutation.telemetry-tenant-bound-payload-free",
            "passed": telemetry_payload_free
            and all(event.identity.solution_id == "whitegoods-lab" for event in telemetry.events),
            "observed": len(telemetry.events),
        },
    ]
    return checks


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

    checks.extend(await _exercise_mutation(connectors[0]))

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
