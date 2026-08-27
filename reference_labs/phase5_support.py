"""Reusable crash-window and restart evidence for Phase-5 industry labs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from data_source_harness.actions import ActionApproval, ActionState, SourceActionPlan
from data_source_harness.connector import ConnectorRegistry
from data_source_harness.durability import (
    ActionOutcomeUnknown,
    DurableActionGateway,
    DurableActionState,
    SQLiteActionJournal,
)
from data_source_harness.policy import PolicyEvaluator, RequestIdentity
from data_source_harness.telemetry import MemoryTelemetrySink

from .phase4_support import LabMutationConnector


@dataclass(frozen=True)
class DurableRecoveryResult:
    outcome_unknown: bool
    blind_replay_blocked: bool
    recovered: bool
    restart_persisted: bool
    one_source_effect: bool
    journal_valid: bool
    payload_free_journal: bool


async def run_durable_recovery(
    action: SourceActionPlan,
    approval: ActionApproval,
    identity: RequestIdentity,
    connector: LabMutationConnector,
    policy: PolicyEvaluator,
    now: datetime,
) -> DurableRecoveryResult:
    registry = ConnectorRegistry()
    registry.register(connector)

    def crash_after_source_effect(_action: SourceActionPlan, _result: object) -> None:
        raise RuntimeError("simulated crash after source effect")

    with TemporaryDirectory(prefix="data-harness-phase5-") as directory:
        journal_path = Path(directory) / "actions.sqlite3"
        first_journal = SQLiteActionJournal(journal_path)
        first_gateway = DurableActionGateway(
            registry,
            policy,
            MemoryTelemetrySink(),
            first_journal,
            now=lambda: now,
            after_mutation=crash_after_source_effect,
        )
        preview = await first_gateway.preview(action, identity)
        outcome_unknown = False
        try:
            await first_gateway.execute(action, preview, identity, approval)
        except ActionOutcomeUnknown:
            outcome_unknown = True

        second_journal = SQLiteActionJournal(journal_path)
        pending = second_journal.pending()
        restart_persisted = (
            len(pending) == 1
            and pending[0].state is DurableActionState.RECONCILIATION_REQUIRED
            and pending[0].attempts == 1
        )
        second_gateway = DurableActionGateway(
            registry,
            policy,
            MemoryTelemetrySink(),
            second_journal,
            now=lambda: now,
        )
        blind_replay_blocked = False
        try:
            await second_gateway.execute(action, preview, identity, approval)
        except ActionOutcomeUnknown:
            blind_replay_blocked = True
        receipt = await second_gateway.reconcile(action, identity)
        replay = await second_gateway.execute(action, preview, identity, approval)
        record = second_journal.get(action.source_id, action.idempotency_key)
        sensitive = [
            str(value).encode()
            for value in (*action.parameters.values(), *action.preconditions.values())
            if value is not None and len(str(value)) >= 4
        ]
        database_bytes = journal_path.read_bytes()
        payload_free = not any(value in database_bytes for value in sensitive)
        return DurableRecoveryResult(
            outcome_unknown,
            blind_replay_blocked,
            receipt.state is ActionState.RECOVERED and replay.state is ActionState.ALREADY_EXECUTED,
            restart_persisted
            and record is not None
            and record.state is DurableActionState.EXECUTED,
            connector.mutation_count == 1,
            second_journal.verify(),
            payload_free,
        )
