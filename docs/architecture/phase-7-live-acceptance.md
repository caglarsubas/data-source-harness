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
and exact-main CI for the harness, ADLC and model-plane. A separate observed
packet proves the four source services on a local ARM64 Docker engine, including
seeded reads, internal networking, zero published ports and public-egress
denial. Python-SDK CI, platform artifact digests and combined-platform execution
evidence remain explicit blockers.

Phase 7 completes only when the same digest-pinned release set passes the four
local source services, protocol suites, local image load/startup, runtime
network-denial and recovery drills, soak/SLO checks and named stakeholder
acceptance. No GCP or OpenShift gate exists in the exit criteria.
