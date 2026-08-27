"""Durable recovery scenario for the cold-chain action source."""

from __future__ import annotations

from reference_labs.phase4_support import BoundedLabActionPolicy, LabMutationConnector
from reference_labs.phase5_support import DurableRecoveryResult, run_durable_recovery

from .phase4 import FIXED_TIME, _approval, _identity, incident_action


async def run_recovery_scenario() -> DurableRecoveryResult:
    action = incident_action()
    return await run_durable_recovery(
        action,
        _approval(action),
        _identity(),
        LabMutationConnector("coldchain.incident-actions", "incidents", "open"),
        BoundedLabActionPolicy(
            "coldchain.incident-actions",
            "incidents",
            "agent.coldchain-responder",
            frozenset({"acknowledge-excursion", "reopen-excursion"}),
        ),
        FIXED_TIME,
    )
