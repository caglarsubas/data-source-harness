# Phase 4 architecture: governed actions and adaptive semantics

Phase 4 enables source side effects without turning connector mutation into an unconstrained agent tool.

## Source-action flow

1. A `SourceActionCapabilityProfile` declares the bounded forward and compensation operations plus mandatory conditional-write and idempotency support. A `SourceActionPlan` names one declared operation; raw parameters remain local while its wire contract exposes only their digest.
2. `ActionGateway.preview` checks mutation capability, source-level idempotency support and local policy. The preview binds the exact action digest, policy digest, expected effects and expiry.
3. Execution rejects stale, denied or mismatched previews, re-evaluates policy and verifies a digest-bound human approval for high-risk actions.
4. The connector receives structured parameters, source-version/value preconditions and an idempotency key. Success requires explicit postcondition evidence.
5. Replays return `already-executed` without repeating the source effect. Reusing a key for a different digest fails closed.
6. A declared compensation is a new previewed, authorized and idempotent source action. The original approval must explicitly allow compensation.
7. Audit entries form a SHA-256 chain and contain identifiers, decisions and source versions—not raw mutation values.

Connector exceptions become explicit failed receipts so a saga can compensate
earlier work. Local audit remains authoritative if telemetry delivery fails;
successful idempotency state is recorded before non-critical telemetry emission.

`ActionSagaCoordinator` applies the same gates to multi-step work and compensates
completed predecessors in reverse order when a later controlled step fails. Its
Phase-4 ledger is process-local. Phase 5 adds the optional SQLite-backed gateway
and source reconciliation boundary; multi-replica workflow coordination remains
a deployment integration requirement.

## Governed semantics and delegation

`GovernedSemanticMemory` is a local adapter around ADLC-owned memory concepts. Agent proposals cannot promote themselves: a human steward must review the lineage-bound assertion, and promoted records are visible only to the declared organization, solution and agents.

`A2AActionDelegationAdapter` accepts one exact, bounded northbound envelope and maps it to the internal action model. Unknown fields, identity mismatch and unexposed operations are rejected. Neither A2A nor MCP appears in the connector implementation ABI.

The machine-readable cross-plane boundary keeps authoritative approvals and
shared-memory records in ADLC, execution receipts and runtime telemetry in the
Python SDK, deployment verification in the OCP lab, and model inference in the
model plane. Phase-4 execution has no synchronous model-plane dependency.

## Evidence boundary

Both reference labs execute, replay and compensate a synthetic action with zero
network dependency. This establishes application semantics only. Phase 5
separately certifies local durable restart reconciliation; production sources,
abrupt host loss, live protocol conformance, deployment evidence and stakeholder
approval remain open.
