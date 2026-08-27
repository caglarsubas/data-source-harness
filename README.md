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
- `orchestra-openshift-reference-lab` remains the deployment, supply-chain, and
  bounded certification-evidence plane.

The control plane is never required synchronously for a production source,
retrieval, tool, or model request.

## Implemented scope through Phase 6

Phase 0 establishes the reusable scaffold:

- capability-negotiated connector and data contracts;
- an untrusted-content decoding boundary;
- append-only, bitemporal semantic assertions;
- default-deny tenant-local authorization seams;
- explicit connected, self-hosted, and air-gapped deployment profiles;
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
cold-chain logistics pilot. A Phase-2 digest lock proves that all 14 wire
contracts remain unchanged, while a core-source scan prevents first-pilot terms
from leaking into the public package.

Phase 4 adds preview-bound and conditionally authorized source actions,
human-approval gates, source-level idempotency, compensations, metadata-only
hash-chained audits, governed semantic-memory promotion, and a bounded A2A-facing
adapter that remains outside the connector ABI. The safety gates run in both the
white-goods and cold-chain labs.

Phase 5 adds a SQLite `FULL`-sync/WAL action journal, restart reconciliation
against source idempotency evidence, fail-closed handling of uncertain outcomes,
and a stateless JSON-RPC northbound action boundary. Agent-visible tool subsets
are scoped, and every call is pinned to the exact tool-catalog digest so a
description change cannot silently alter a previously inspected tool. This is
an adapter boundary for later MCP/A2A hosting, not a claim of official protocol
conformance.

Phase 6 moves connector calls behind replaceable operating-system process
workers with bounded request/response sizes, deadlines, cancellation,
parallelism and a sanitized environment. It adds MCP `2026-07-28` and A2A `1.0`
profile adapters, a cross-plane evidence ledger that cannot collapse CI into
runtime acceptance, and a signed disconnected-transfer packet with OpenShift
security templates. The certificate deliberately records upstream protocol
suites, image mirroring, live deployment and stakeholder acceptance as missing.

## Developer quick start

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run harness-contracts validate
uv run harness-contracts phase0-gate --output phase0-report.json
make phase6
```

The built wheel embeds the versioned schemas, contract catalog, deployment
profiles, and neutral reference-lab manifest under
`data_source_harness/resources` for offline distribution.

## Safety posture

- Reads and writes are distinct capabilities; mutation is denied unless a
  connector and policy both declare it.
- Credentials are references resolved inside the tenant perimeter and never
  enter manifests, telemetry, or evidence.
- `air-gapped` mode denies every undeclared or non-perimeter route.
- Retrieved content is untrusted data, not executable instruction.
- Missing, partial, stale, ambiguous, and unauthorized evidence remain visible
  in coverage statements rather than being converted into success.

See [Phase 6 architecture](docs/architecture/phase-6-runtime-scaffold.md) for
connector-worker isolation, protocol profiles and cross-plane evidence states.

The staged [development roadmap](docs/development-roadmap.md) defines the
white-goods and cold-chain pilots without coupling the core to either industry.

See the [white-goods lab](reference_labs/white_goods/README.md) for its mock
data, representative technology topology, GQM scorecard, and explicit runtime
evidence boundary.

See the [cold-chain lab](reference_labs/cold_chain/README.md) for the second-pilot
fixtures, generated carrier connector and Phase-3 GQM certificate.
