# Phase 7 architecture: live acceptance campaign

Phase 7 uses a fail-closed evidence matrix rather than a single deployment flag.
The matrix covers five components: data-source-harness, ADLC, Python-SDK,
OCP-reference-lab and model-plane. Each component has an independent source,
PR-CI, exact-main-CI, publication, mirror, deployment, runtime, fault, soak,
protocol-conformance and stakeholder observation.

Every observation binds the exact source revision. Publication and every later
stage must also bind the artifact digest declared by the release set. The
campaign parser recomputes the canonical release-set digest, blocker list and
`accepted` value. A producer cannot set `accepted: true`, remove blockers, reuse
evidence from another revision or substitute CI for runtime acceptance.

The live data estate is represented separately by exactly four target shapes:
PostgreSQL, S3-compatible storage, Kafka-compatible streaming and REST. Targets
carry connector identities and `credential-ref://` endpoint references, never
URLs or credentials. A verified target additionally requires a digest-pinned
image, an observation time and evidence references.

`CostBoundary` records whether provisioning was authorized and which resources
or mutations occurred. The committed readiness snapshot is deliberately
observation-only: authorization is false and both mutation lists are empty.
The certificate makes no cloud API calls and does not start Docker.

The initial snapshot observes exact source revisions for all five components.
It also records exact-main CI for the harness, ADLC, OCP-reference-lab and
model-plane. Python-SDK has no check-run evidence at its pinned revision. All
artifact digests, live sources and later acceptance stages remain explicit
blockers.

Full Phase 7 begins only after an operator supplies approved image and artifact
digests and authorizes an execution environment. Completion still requires the
same release set to pass live services, upstream protocol suites, disconnected
mirroring, OpenShift deployment, zero-egress and recovery drills, soak/SLOs and
named stakeholder acceptance.
