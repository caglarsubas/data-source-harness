# Orchestra Data-Source Harness

The Orchestra Data-Source Harness is the tenant-local data context and execution
plane for multi-agent systems. It normalizes how agents discover sources,
resolve governed semantics, retrieve evidence, and execute bounded reads across
heterogeneous databases, APIs, documents, event streams, search systems, and
graphs.

This repository deliberately does **not** duplicate the surrounding Orchestra
planes:

- `agent-hook-v2` remains the asynchronous control, governance, evaluation,
  audit, and release-evidence plane.
- `planeon-orchestra-python-sdk` remains the telemetry-first SDK and optional
  signed tenant-runtime/MCP execution plane.
- `llm_inference_engine` remains the tenant model plane for chat, embeddings,
  reranking, structured output, and guardrails.
- `orchestra-openshift-reference-lab` is retained only as historical Phase 6/6.5
  packaging evidence. It is not part of the supported runtime or Phase 7 release set.

The control plane is never required synchronously for a production source,
retrieval, tool, or model request.

## Implemented scope through Phase 7 readiness

Phase 0 establishes the reusable scaffold:

- capability-negotiated connector and data contracts;
- an untrusted-content decoding boundary;
- append-only, bitemporal semantic assertions;
- default-deny tenant-local authorization seams;
- explicit connected, self-hosted, air-gapped, and laptop-local deployment profiles;
- bounded coverage and provenance outputs;
- a connector conformance runner;
- JSON Schemas, positive/negative fixtures, and a cross-plane compatibility
  lock;
- executable tests and a machine-readable Phase-0 gate report.

Industry logic does not belong in the core package. White-goods manufacturing
is implemented separately as the first `IndustryDomainPack` and reference lab.

Phase 1 supplies the heterogeneous reference estate. Phase 2 adds steward-approved
semantic mappings, drift quarantine, freshness-aware routing, monotonic CDC
checkpoints, bounded field/relationship planning, grounded answer envelopes and
promotion-readiness evidence without duplicating ADLC's final release decision.

Phase 3 adds a deterministic industry-pack factory, OpenAPI-driven connector
scaffolding, signed connector archives with CycloneDX SBOMs, and a second
cold-chain logistics pilot. The immutable Phase-2 digest lock plus an explicit
compatibility-evolution ledger preserves contract history, while a core-source
scan prevents first-pilot terms from leaking into the public package.

Phase 4 adds preview-bound and conditionally authorized source actions,
human-approval gates, source-level idempotency, compensations, metadata-only
hash-chained audits, governed semantic-memory promotion, and a bounded A2A-facing
adapter that remains outside the connector ABI. The safety gates run in both the
white-goods and cold-chain labs.

Phase 5 adds a SQLite `FULL`-sync/WAL action journal with a keyed integrity
chain, restart reconciliation
against source idempotency evidence, fail-closed handling of uncertain outcomes,
and a stateless JSON-RPC northbound action boundary. Agent-visible tool subsets
are scoped, and every call is pinned to the exact tool-catalog digest so a
description change cannot silently alter a previously inspected tool. This is
an adapter boundary for later MCP/A2A hosting, not a claim of official protocol
conformance.

Phase 6 moved connector calls behind replaceable operating-system process
workers with bounded request/response sizes, deadlines, cancellation,
parallelism and a sanitized environment. It adds MCP `2026-07-28` and A2A `1.0`
profile adapters, a cross-plane evidence ledger that cannot collapse CI into
runtime acceptance, and produced a signed disconnected-transfer packet with
OpenShift security templates. Those templates now remain historical and are not
executed by the roadmap.

Phase 6.5 closes the repository-level integration spine: bounded planner output
executes through the canonical gateway, the same connector ABI crosses a
hardened subprocess boundary, and a reusable coordinator produces explicit
expected-source coverage and deduplicated lineage. Human approvals require a
cryptographically verified authority, decoders and archives are resource
bounded, and tenant-neutral seams publish redacted execution evidence to the
Python SDK/ADLC while keeping model-plane reranking locally governed. The
air-gap packet includes a pinned dependency wheelhouse and runtime container
recipe. Previously produced OCP assets remain immutable historical artifacts;
none is a current execution requirement.

Phase 7 readiness is laptop-local in core version `0.13.0`. Its fail-closed
campaign covers the harness, ADLC, Python-SDK and model-plane plus local
PostgreSQL, S3-compatible, Kafka-compatible and REST services. Mirror and cluster
deployment gates are replaced by local image-load and local-startup gates.
Images must already exist on the laptop (`pull_policy: never`), services expose
no host ports, and the internal network has no external route. GCP, OpenShift
and remote-cluster provisioning are prohibited by contract and an automation
scan. The readiness snapshot is not a completed acceptance claim.

The Phase 7 local-source lab now executes real PostgreSQL, S3-compatible MinIO,
Kafka-compatible Redpanda and an authenticated OpenAPI-backed REST service on
the laptop. It seeds representative data, verifies queries/consumption,
confirms zero published ports and proves public egress is denied. Its immutable
ARM64 image lock and schema-validated evidence remove all source-service
verification blockers while leaving combined-platform blockers explicit.

The Phase 7 local cross-plane contract lab executes mature component code from
exact local `origin/main` revisions. Python-SDK constructs a runtime receipt,
ADLC validates the same bytes and rejects a forged lifecycle transition in a
no-network container, and model-plane serves its real health and rerank routes
under a tenant identity. The harness applies its bounded ranking guard and
records one schema-validated packet. This proves contract interoperability,
not full production images, ADLC ingestion, model loading or platform startup.

The local harness-runtime lab builds an ARM64 acceptance image from the
preloaded Python base, the harness wheel and a pinned wheelhouse. On the same
internal network, real PostgreSQL, S3-compatible, Kafka-compatible and REST
connectors run through `HarnessGateway`. The evidence covers discovery, bounded
queries, untrusted decoding, semantic resolution, exact provenance and
read-only action denial without published ports or external resources. The
same one-shot runtime now performs one allowlisted PostgreSQL mutation through
preview, cryptographically bound human approval, optimistic concurrency and
source-persisted idempotency; it proves replay safety across a fresh gateway,
denies a stale write and compensates back to the seeded value before teardown.

## Developer quick start

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run harness-contracts validate
uv run harness-contracts phase0-gate --output phase0-report.json
make phase7-local-readiness
# Explicit laptop-only evidence refreshes (not run by hosted CI):
make phase7-local-sources
make phase7-local-cross-plane
make phase7-local-harness
```

To refresh the source-service evidence on a laptop where the locked images are
already present, run `make phase7-local-sources`. This command builds only the
mock REST image, starts the internal Compose topology, records evidence and
removes the containers and volumes. It never provisions cloud or cluster
resources.

The built wheel embeds the versioned schemas, contract catalog, deployment
profiles, and neutral reference-lab manifest under
`data_source_harness/resources` for offline distribution.

## Safety posture

- Reads and writes are distinct capabilities; mutation is denied unless a
  connector and policy both declare it.
- Credentials are references resolved inside the tenant perimeter and never
  enter manifests, telemetry, or evidence.
- `local-laptop` mode allows only declared service aliases and loopback;
  external telemetry and registry mirrors are disabled.
- Retrieved content is untrusted data, not executable instruction.
- Missing, partial, stale, ambiguous, and unauthorized evidence remain visible
  in coverage statements rather than being converted into success.

See [Phase 7 local-laptop architecture](docs/architecture/phase-7-live-acceptance.md)
for the evidence matrix, local-source identities, cost boundary and completion
rules.

The staged [development roadmap](docs/development-roadmap.md) defines the
white-goods and cold-chain pilots without coupling the core to either industry.

See the [white-goods lab](reference_labs/white_goods/README.md) for its mock
data, representative technology topology, GQM scorecard, and explicit runtime
evidence boundary.

See the [cold-chain lab](reference_labs/cold_chain/README.md) for the second-pilot
fixtures, generated carrier connector and Phase-3 GQM certificate.
