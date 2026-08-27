# Phase 5 architecture: durable recovery and protocol edge

Phase 5 closes the process-local action replay gap without coupling source
connectors to an agent protocol.

## Durable action lifecycle

`DurableActionGateway` applies the Phase-4 preview, approval and execute-time
authorization gates before binding `(source_id, idempotency_key)` to the exact
action digest. `SQLiteActionJournal` persists `prepared` and then `executing`
before connector dispatch. SQLite runs in WAL mode with `synchronous=FULL`.

After dispatch, an exception or injected crash-window failure is treated as an
unknown outcome—not as proof of failure. The journal moves to
`reconciliation-required`. A second `execute` call is rejected and cannot reach
the connector. Recovery must call the source's separate `reconcile` operation,
which proves the idempotency key, action identity, postcondition and source
version. Only that proof creates a `recovered` receipt and closes the durable
record. A subsequent replay returns the stored receipt without a new effect.

The journal stores action and parameter digests, identifiers, state, versions
and receipts. It does not persist raw mutation parameters or precondition
values. Its event rows form a persistent SHA-256 chain. The SQLite implementation
is the on-premises single-node reference pillar; it is not a multi-replica
consensus or production database-HA claim.

## Northbound protocol boundary

`NorthboundActionAdapter` is stateless JSON-RPC 2.0 with an internal
`data.harness.northbound/v1` version. It implements the narrow shapes
`tools/list` and `tools/call` so an MCP or A2A host can adapt them later:

1. the caller receives only tools allowed for its agent identity;
2. the response contains the immutable catalog digest but does not disclose
   other agents' scope;
3. every tool call must present that digest;
4. changed descriptions, operations or scopes change the digest and reject the
   stale call;
5. exact arguments are mapped to a `SourceActionPlan`; the adapter cannot
   execute a connector directly.

The existing gateway remains authoritative for preview, policy, approval,
conditional write, durable dispatch and audit. Connector source contains no
JSON-RPC/northbound vocabulary. This is intentionally not labelled official MCP
or A2A conformance.

## Air-gapped operation and evidence boundary

The journal, adapter, schemas and two industry scenarios use only local package
resources and Python's standard library at runtime. Certification monkeypatches
socket connection attempts to fail and records zero attempts. Phase 6 must still
prove mirrored images, live OpenShift network policy, production connector
workers, protocol conformance and stakeholder acceptance as separate evidence.
