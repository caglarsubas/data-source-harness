# Phase 7 architecture: laptop-local acceptance campaign

Phase 7 uses a fail-closed evidence matrix for a runtime that fits entirely on
one developer laptop. The release set covers four locally runnable components:
data-source-harness, ADLC, Python-SDK and model-plane. OCP-reference-lab is not a
runtime component; its older packaging evidence remains historical only.

Each component has independent source, PR-CI, exact-main-CI, publication,
local-image-load, local-startup, runtime, fault, soak, protocol-conformance and
stakeholder observations. Every observation binds an exact source revision.
Publication and every later stage also bind the artifact digest declared by the
release set. The parser recomputes the release-set digest, blocker list and
`accepted` value, so a producer cannot turn missing or mismatched evidence into
acceptance.

The local data estate contains PostgreSQL, S3-compatible storage,
Kafka-compatible streaming and REST. Targets carry connector identities and
`credential-ref://` references rather than URLs or credentials. A verified
target additionally requires a digest-pinned local image, timestamp and evidence
references.

## Enforced operating boundary

- `DeploymentMode.LOCAL_LAPTOP` allows only declared Compose service aliases
  and loopback; external telemetry and an artifact mirror are disabled.
- Compose uses `pull_policy: never`, no host-published ports and an
  `internal: true` network. Approved images must be preloaded on the laptop.
- `CostBoundary` rejects `provisioningAuthorized: true`, resource creation and
  external mutations.
- the automation guard fails on GCP CLIs/actions, cluster create/apply commands
  and infrastructure apply/destroy commands in executable workflow surfaces.
- GitHub source hosting and CI may validate code, but application services and
  acceptance workloads run locally and do not create remote runtime resources.

The readiness snapshot observes exact source revisions for all four components
and exact-main CI for ADLC and model-plane. The new harness candidate is
deliberately blocked on exact-main CI until it is merged. A separate observed
packet proves the four source services on a local ARM64 Docker engine, including
seeded reads, internal networking, zero published ports and public-egress
denial. A second packet executes exact local Python-SDK receipt construction,
exact ADLC receipt parsing in a no-network probe container and the model-plane's
real health/rerank routes under a tenant identity; harness ranking governance
binds the result. The packet hashes only the exercised source surfaces and does
not reinterpret the probe container as a production ADLC artifact. Python-SDK
CI and the other platform artifact digests remain explicit blockers.

A third packet binds the harness candidate revision to a locally built ARM64
image and pinned 18-wheel dependency set. The image starts as a one-shot
acceptance workload on the internal network and executes real PostgreSQL, S3,
Kafka and REST connectors through `HarnessGateway`. Discovery, bounded query
planning, untrusted decoding, semantic resolution, exact provenance,
tenant-bound telemetry and read-only action denial pass. This closes only the
harness artifact-identity, local-image-load, local-startup and runtime gates;
publication, exact-main CI, fault, soak, protocol and stakeholder gates remain.

Phase 7 completes only when the same digest-pinned release set passes the four
local source services, protocol suites, local image load/startup, runtime
network-denial and recovery drills, soak/SLO checks and named stakeholder
acceptance. No GCP or OpenShift gate exists in the exit criteria.
