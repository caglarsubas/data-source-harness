# Phase 6 architecture: runtime scaffold and acceptance packet

Phase 6 turns the in-process reference connectors into replaceable worker
processes and creates versioned handoffs to the surrounding ADLC platform. It
does not duplicate production workflow durability already owned by the Python
SDK or deployment certification owned by the OpenShift reference lab.

## Connector-worker boundary

`ConnectorWorkerClient` invokes an absolute executable directly—never through a
shell—and exchanges exactly one bounded JSON-line request and response using
`harness.worker/v1`. Each operation runs in a replaceable child process.

The boundary enforces:

- operation deadline with child termination;
- cancellation with child termination;
- request and response byte ceilings;
- a semaphore-backed parallelism ceiling;
- exact response correlation and envelope validation;
- a minimal environment limited to process settings; credentials remain
  references and are resolved inside the tenant-owned worker;
- no child stderr content in caller-facing errors.

The white-goods worker exercises PostgreSQL-shaped tabular queries, S3-shaped
object metadata, Kafka-shaped checkpoint polling and REST-shaped records over
the deterministic corpus. These are wire/behavior fixtures, not live services or
container certification. Process profiles truthfully declare `networkMode:
host`; network isolation is not claimed until a digest-pinned container and live
OpenShift policy are verified.

## Protocol profiles

`Mcp20260728ActionServer` follows the stateless MCP `2026-07-28` tools profile:
every request carries protocol/client metadata, tool lists are deterministic and
authorization-scoped, cache scope is private, and Streamable HTTP method/name
headers must match the JSON body. Tool calls carry the harness catalog digest
and return only a bounded action plan; preview, policy, approval and execution
remain downstream.

`A2A10ActionServer` publishes an A2A `1.0` Agent Card and accepts the JSON-RPC
`SendMessage` profile with one current-form JSON data part. It maps only a
pre-authorized source action and cannot execute the connector.

These checks were derived from the current official specifications. They are
not a substitute for the projects' upstream conformance suites:

- https://modelcontextprotocol.io/specification/2026-07-28
- https://a2a-protocol.org/latest/specification

## Cross-plane ownership and evidence

`CrossPlaneEvidenceSet` records contract, CI, publication, deployment, runtime,
fault and stakeholder states independently for ADLC, Python-SDK, OCP-reference-
lab and model-plane revisions. A passed or failed claim requires an observation
time and an evidence reference. Missing states cannot carry invented evidence.
`combinedRuntimeAccepted` becomes true only when every required claim passes.

The Phase-6 packet pins the live default-branch revisions observed during its
design. Only harness-side contract compatibility is passed. Upstream CI,
publication, deployment, runtime, fault and acceptance remain missing until a
separate campaign observes them.

## Disconnected transfer packet

The deterministic packet contains the harness wheel, schemas, compatibility
evidence, deployment profiles and OpenShift templates; its HMAC lab signature,
checksums and CycloneDX file SBOM verify offline. The template is default-deny,
non-root, read-only and drops Linux capabilities.

The image remains `IMAGE_DIGEST_REQUIRED`. The readiness record therefore keeps
image resolution, signature mirroring, deployment, zero-egress runtime proof and
stakeholder acceptance false. OpenShift disconnected deployments require an
internal registry and a supported mirroring workflow; the current Red Hat
guidance is https://docs.redhat.com/en/documentation/openshift_container_platform/4.20/html-single/disconnected_environments/index.
