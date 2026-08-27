"""Durable recovery scenario for the white-goods action source."""

from __future__ import annotations

from reference_labs.phase4_support import BoundedLabActionPolicy, LabMutationConnector
from reference_labs.phase5_support import DurableRecoveryResult, run_durable_recovery

from .phase4 import FIXED_TIME, _approval, _identity, service_action


async def run_recovery_scenario() -> DurableRecoveryResult:
    action = service_action()
    return await run_durable_recovery(
        action,
        _approval(action),
        _identity(),
        LabMutationConnector(
            "whitegoods.service-actions",
            "service_appointments",
            "2026-09-01T09:00:00Z",
        ),
        BoundedLabActionPolicy(
            "whitegoods.service-actions",
            "service_appointments",
            "agent.whitegoods-service",
            frozenset({"reschedule-appointment", "restore-appointment"}),
        ),
        FIXED_TIME,
    )
