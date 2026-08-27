"""SQLite-backed action recovery that never blindly replays an uncertain mutation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from .actions import (
    ActionApproval,
    ActionExecutionFailed,
    ActionGateway,
    ActionPreview,
    ActionState,
    IdempotencyConflict,
    SourceActionPlan,
    SourceMutationReceipt,
)
from .connector import Capability, ConnectorRegistry
from .models import Scalar
from .policy import PolicyDenied, PolicyEvaluator, RequestIdentity
from .telemetry import TelemetrySink


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class DurableActionState(StrEnum):
    PREPARED = "prepared"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    RECONCILIATION_REQUIRED = "reconciliation-required"


class ActionOutcomeUnknown(RuntimeError):
    """The source may have applied an action; source reconciliation is required."""


@dataclass(frozen=True)
class DurableActionRecord:
    source_id: str
    idempotency_key: str
    action_id: str
    action_digest: str
    state: DurableActionState
    policy_decision_id: str
    started_at: datetime
    updated_at: datetime
    attempts: int
    source_version: str | None
    receipt: SourceMutationReceipt | None
    journal_digest: str

    def to_contract(self) -> dict[str, Any]:
        return {
            "schemaVersion": "data.harness/v1",
            "sourceId": self.source_id,
            "idempotencyKey": self.idempotency_key,
            "actionId": self.action_id,
            "actionDigest": self.action_digest,
            "state": self.state.value,
            "policyDecisionId": self.policy_decision_id,
            "startedAt": self.started_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
            "attempts": self.attempts,
            "sourceVersion": self.source_version,
            "receiptId": self.receipt.receipt_id if self.receipt else None,
            "journalDigest": self.journal_digest,
        }


class SQLiteActionJournal:
    """Durable action/idempotency ledger with a metadata-only SHA-256 event chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS action_records (
                    source_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    action_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    policy_decision_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    source_version TEXT,
                    receipt_json TEXT,
                    journal_digest TEXT NOT NULL,
                    PRIMARY KEY (source_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS action_events (
                    sequence INTEGER PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    action_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    attributes_json TEXT NOT NULL,
                    previous_digest TEXT NOT NULL,
                    digest TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        event_type: str,
        action_id: str,
        occurred_at: datetime,
        attributes: Mapping[str, Scalar],
    ) -> str:
        previous_row = connection.execute(
            "SELECT sequence, digest FROM action_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = int(previous_row["sequence"]) + 1 if previous_row else 1
        previous = previous_row["digest"] if previous_row else "sha256:" + "0" * 64
        body = {
            "sequence": sequence,
            "event_type": event_type,
            "action_id": action_id,
            "occurred_at": occurred_at.isoformat(),
            "attributes": dict(attributes),
            "previous_digest": previous,
        }
        digest = _digest(body)
        connection.execute(
            "INSERT INTO action_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sequence,
                event_type,
                action_id,
                occurred_at.isoformat(),
                json.dumps(dict(attributes), sort_keys=True, separators=(",", ":")),
                previous,
                digest,
            ),
        )
        return digest

    def prepare(
        self, action: SourceActionPlan, policy_decision_id: str, now: datetime
    ) -> DurableActionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM action_records WHERE source_id = ? AND idempotency_key = ?",
                (action.source_id, action.idempotency_key),
            ).fetchone()
            if row is not None:
                record = self._record(row)
                if record.action_digest != action.digest:
                    raise IdempotencyConflict("idempotency key was already bound to another action")
                return record
            digest = self._append_event(
                connection,
                DurableActionState.PREPARED.value,
                action.action_id,
                now,
                {"source_id": action.source_id},
            )
            connection.execute(
                """INSERT INTO action_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action.source_id,
                    action.idempotency_key,
                    action.action_id,
                    action.digest,
                    DurableActionState.PREPARED.value,
                    policy_decision_id,
                    now.isoformat(),
                    now.isoformat(),
                    0,
                    None,
                    None,
                    digest,
                ),
            )
        record = self.get(action.source_id, action.idempotency_key)
        assert record is not None
        return record

    def begin(self, action: SourceActionPlan, now: datetime) -> DurableActionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM action_records WHERE source_id = ? AND idempotency_key = ?",
                (action.source_id, action.idempotency_key),
            ).fetchone()
            if row is None:
                raise KeyError("action must be prepared before execution")
            record = self._record(row)
            if record.action_digest != action.digest:
                raise IdempotencyConflict("idempotency key was already bound to another action")
            if record.state is DurableActionState.EXECUTED:
                return record
            if record.state is not DurableActionState.PREPARED:
                raise ActionOutcomeUnknown(
                    f"action state {record.state.value} forbids automatic replay"
                )
            digest = self._append_event(
                connection,
                DurableActionState.EXECUTING.value,
                action.action_id,
                now,
                {"source_id": action.source_id, "attempt": record.attempts + 1},
            )
            connection.execute(
                """UPDATE action_records
                   SET state = ?, updated_at = ?, attempts = ?, journal_digest = ?
                   WHERE source_id = ? AND idempotency_key = ?""",
                (
                    DurableActionState.EXECUTING.value,
                    now.isoformat(),
                    record.attempts + 1,
                    digest,
                    action.source_id,
                    action.idempotency_key,
                ),
            )
        updated = self.get(action.source_id, action.idempotency_key)
        assert updated is not None
        return updated

    def complete(
        self, action: SourceActionPlan, receipt: SourceMutationReceipt, now: datetime
    ) -> DurableActionRecord:
        return self._finish(
            action,
            DurableActionState.EXECUTED,
            receipt,
            receipt.source_version,
            now,
        )

    def fail(
        self, action: SourceActionPlan, receipt: SourceMutationReceipt, now: datetime
    ) -> DurableActionRecord:
        return self._finish(action, DurableActionState.FAILED, receipt, receipt.source_version, now)

    def require_reconciliation(
        self, action: SourceActionPlan, now: datetime, reason: str
    ) -> DurableActionRecord:
        return self._finish(
            action,
            DurableActionState.RECONCILIATION_REQUIRED,
            None,
            None,
            now,
            reason,
        )

    def _finish(
        self,
        action: SourceActionPlan,
        state: DurableActionState,
        receipt: SourceMutationReceipt | None,
        source_version: str | None,
        now: datetime,
        reason: str | None = None,
    ) -> DurableActionRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM action_records WHERE source_id = ? AND idempotency_key = ?",
                (action.source_id, action.idempotency_key),
            ).fetchone()
            if row is None or row["action_digest"] != action.digest:
                raise IdempotencyConflict("durable action binding is missing or mismatched")
            attributes: dict[str, Scalar] = {"source_id": action.source_id}
            if source_version is not None:
                attributes["source_version"] = source_version
            if reason is not None:
                attributes["reason"] = reason
            digest = self._append_event(connection, state.value, action.action_id, now, attributes)
            receipt_json = (
                json.dumps(receipt.to_contract(), sort_keys=True, separators=(",", ":"))
                if receipt
                else None
            )
            connection.execute(
                """UPDATE action_records
                   SET state = ?, updated_at = ?, source_version = ?, receipt_json = ?,
                       journal_digest = ?
                   WHERE source_id = ? AND idempotency_key = ?""",
                (
                    state.value,
                    now.isoformat(),
                    source_version,
                    receipt_json,
                    digest,
                    action.source_id,
                    action.idempotency_key,
                ),
            )
        updated = self.get(action.source_id, action.idempotency_key)
        assert updated is not None
        return updated

    def get(self, source_id: str, idempotency_key: str) -> DurableActionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM action_records WHERE source_id = ? AND idempotency_key = ?",
                (source_id, idempotency_key),
            ).fetchone()
        return self._record(row) if row else None

    def pending(self) -> tuple[DurableActionRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM action_records
                   WHERE state IN (?, ?) ORDER BY source_id, idempotency_key""",
                (
                    DurableActionState.EXECUTING.value,
                    DurableActionState.RECONCILIATION_REQUIRED.value,
                ),
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def verify(self) -> bool:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM action_events ORDER BY sequence").fetchall()
        previous = "sha256:" + "0" * 64
        for row in rows:
            body = {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "action_id": row["action_id"],
                "occurred_at": row["occurred_at"],
                "attributes": json.loads(row["attributes_json"]),
                "previous_digest": previous,
            }
            if row["previous_digest"] != previous or row["digest"] != _digest(body):
                return False
            previous = row["digest"]
        return True

    @staticmethod
    def _record(row: sqlite3.Row) -> DurableActionRecord:
        receipt_data = json.loads(row["receipt_json"]) if row["receipt_json"] else None
        receipt = None
        if receipt_data:
            receipt = SourceMutationReceipt(
                receipt_data["receiptId"],
                receipt_data["actionId"],
                receipt_data["actionDigest"],
                receipt_data["idempotencyKey"],
                ActionState(receipt_data["state"]),
                datetime.fromisoformat(receipt_data["startedAt"]),
                datetime.fromisoformat(receipt_data["completedAt"]),
                receipt_data["sourceVersion"],
                receipt_data["policyDecisionId"],
                receipt_data["auditDigest"],
                receipt_data["compensationOf"],
            )
        return DurableActionRecord(
            row["source_id"],
            row["idempotency_key"],
            row["action_id"],
            row["action_digest"],
            DurableActionState(row["state"]),
            row["policy_decision_id"],
            datetime.fromisoformat(row["started_at"]),
            datetime.fromisoformat(row["updated_at"]),
            row["attempts"],
            row["source_version"],
            receipt,
            row["journal_digest"],
        )


class DurableActionGateway(ActionGateway):
    """Action gateway with write-ahead execution and source-backed recovery."""

    def __init__(
        self,
        registry: ConnectorRegistry,
        policy: PolicyEvaluator,
        telemetry: TelemetrySink,
        journal: SQLiteActionJournal,
        *,
        now: Callable[[], datetime] | None = None,
        after_mutation: Callable[[SourceActionPlan, Mapping[str, Any]], None] | None = None,
    ) -> None:
        super().__init__(registry, policy, telemetry, now=now)
        self.journal = journal
        self.after_mutation = after_mutation

    async def execute(
        self,
        action: SourceActionPlan,
        preview: ActionPreview,
        identity: RequestIdentity,
        approval: ActionApproval | None = None,
    ) -> SourceMutationReceipt:
        now = self.now()
        self._validate_preview(action, preview, identity, now)
        self._validate_approval(action, approval, identity, now)
        decision = await self._authorize(action, identity, "execute")
        if not decision.allowed:
            raise PolicyDenied(decision)
        record = self.journal.prepare(action, decision.decision_id, now)
        if record.state is DurableActionState.EXECUTED and record.receipt is not None:
            audit = self.audit.append(
                "replayed", action.action_id, now, {"receipt_id": record.receipt.receipt_id}
            )
            await self._emit(
                "replayed", action, identity, {"receipt_id": record.receipt.receipt_id}
            )
            return replace(
                record.receipt,
                state=ActionState.ALREADY_EXECUTED,
                completed_at=now,
                audit_digest=audit.digest,
            )
        self.journal.begin(action, now)
        connector = self.registry.get(action.source_id, Capability.MUTATE)
        request = {
            "action_id": action.action_id,
            "asset_id": action.asset_id,
            "operation": action.operation,
            "parameters": dict(action.parameters),
            "preconditions": dict(action.preconditions),
            "idempotency_key": action.idempotency_key,
        }
        try:
            result = await connector.mutate(request)
            if not isinstance(result, Mapping):
                raise TypeError("connector mutation result must be a mapping")
            if self.after_mutation is not None:
                self.after_mutation(action, result)
        except Exception as exc:
            self.journal.require_reconciliation(
                action, self.now(), "outcome-unknown-after-dispatch"
            )
            await self._emit("reconciliation-required", action, identity, {})
            raise ActionOutcomeUnknown(
                f"source outcome is unknown for action {action.action_id}; reconcile before retry"
            ) from exc
        completed = self.now()
        success = result.get("success") is True and result.get("postconditions_met") is True
        state = ActionState.EXECUTED if success else ActionState.FAILED
        audit = self.audit.append(
            state.value,
            action.action_id,
            completed,
            {"source_version": str(result.get("source_version", "unknown"))},
        )
        receipt = SourceMutationReceipt(
            f"receipt:{action.action_id}:{len(self.audit.entries)}",
            action.action_id,
            action.digest,
            action.idempotency_key,
            state,
            now,
            completed,
            str(result.get("source_version", "unknown")),
            decision.decision_id,
            audit.digest,
        )
        if not success:
            self.journal.fail(action, receipt, completed)
            await self._emit(
                state.value, action, identity, {"source_version": receipt.source_version}
            )
            raise ActionExecutionFailed(receipt)
        self.journal.complete(action, receipt, completed)
        await self._emit(state.value, action, identity, {"source_version": receipt.source_version})
        return receipt

    async def reconcile(
        self, action: SourceActionPlan, identity: RequestIdentity
    ) -> SourceMutationReceipt:
        decision = await self._authorize(action, identity, "reconcile")
        if not decision.allowed:
            raise PolicyDenied(decision)
        record = self.journal.get(action.source_id, action.idempotency_key)
        if record is None or record.action_digest != action.digest:
            raise IdempotencyConflict("durable action binding is missing or mismatched")
        if record.state is DurableActionState.EXECUTED and record.receipt is not None:
            return record.receipt
        if record.state not in {
            DurableActionState.EXECUTING,
            DurableActionState.RECONCILIATION_REQUIRED,
        }:
            raise ActionOutcomeUnknown(
                f"action state {record.state.value} cannot be reconciled as successful"
            )
        connector = self.registry.get(action.source_id, Capability.MUTATE)
        reconcile = getattr(connector, "reconcile", None)
        if reconcile is None:
            raise ActionOutcomeUnknown(
                "connector does not expose source idempotency reconciliation"
            )
        result = await reconcile(
            {
                "action_id": action.action_id,
                "idempotency_key": action.idempotency_key,
                "action_digest": action.digest,
            }
        )
        if (
            not isinstance(result, Mapping)
            or result.get("applied") is not True
            or result.get("postconditions_met") is not True
        ):
            self.journal.require_reconciliation(action, self.now(), "source-outcome-unresolved")
            raise ActionOutcomeUnknown("source could not prove whether the action was applied")
        completed = self.now()
        source_version = str(result.get("source_version", "unknown"))
        audit = self.audit.append(
            ActionState.RECOVERED.value,
            action.action_id,
            completed,
            {"source_version": source_version},
        )
        receipt = SourceMutationReceipt(
            f"receipt:{action.action_id}:recovered",
            action.action_id,
            action.digest,
            action.idempotency_key,
            ActionState.RECOVERED,
            record.started_at,
            completed,
            source_version,
            decision.decision_id,
            audit.digest,
        )
        self.journal.complete(action, receipt, completed)
        await self._emit("recovered", action, identity, {"source_version": source_version})
        return receipt


def utc_now() -> datetime:
    """Small injectable default useful to journal consumers outside the gateway."""

    return datetime.now(UTC)
