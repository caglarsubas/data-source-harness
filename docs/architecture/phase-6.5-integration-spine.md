# Phase 6.5 architecture: integration spine

Phase 6.5 connects the previously certified pillars without moving ownership
from the surrounding ADLC platform planes. Its vertical path is:

```text
bounded plan -> local policy -> HarnessGateway -> Connector ABI
                                      |-> in-process pilot connector
                                      |-> WorkerBackedConnector -> bounded subprocess RPC
              -> CrossSourceCoordinator -> coverage + lineage
              -> redacted SDK receipt -> ADLC evidence reference
              -> governed tenant-bound model-plane rerank
```

`HarnessGateway` is the mandatory enforcement point for source capability,
policy, deadline, parallelism, result size, finite payload, source-version,
lineage and search ACL invariants. `WorkerBackedConnector` translates this same
ABI to `harness.worker/v1`; it does not create a second connector contract.

`CrossSourceCoordinator` executes independent source steps concurrently. The
plan declares the expected source universe before execution. Every source must
therefore appear as included or explicitly excluded, and cancellation remains a
caller control signal rather than an ordinary source failure.

Human actions require an injected `ApprovalVerifier`. The bundled HMAC authority
is an offline lab implementation whose signature binds issuer, audience, nonce,
action, policy, tenant, agent, request, time and compensation scope. Production
ADLC deployments replace it with their authoritative verifier. The durable
SQLite journal uses a keyed HMAC chain and binds prepare events to the action
digest, policy decision, source and idempotency key.

Cross-plane interfaces are deliberately small and tenant-neutral. The SDK sink
receives a redacted coverage/lineage digest, ADLC receives that evidence plus the
SDK receipt identity, and model-plane reranking receives bounded candidates and
tenant identity. These local interfaces prove harness behavior only; they do not
claim that an upstream component ran or accepted the evidence.

The disconnected packet contains the application and dependency wheels,
CycloneDX dependency graph, runtime container recipe, status endpoint,
OpenShift service/configuration/probes/network policies and an `oc-mirror` v2
input template. The wheelhouse carries a target declaration and checksums, and
CI actions are pinned to exact revisions. Image digests, mirroring, live
deployment, zero-egress runtime and stakeholder acceptance remain explicit
blockers until Phase 7 observes them.
