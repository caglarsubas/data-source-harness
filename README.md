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

## Implemented scope through Phase 2

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

## Developer quick start

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv run harness-contracts validate
uv run harness-contracts phase0-gate --output phase0-report.json
make phase2
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

See [Phase 2 architecture](docs/architecture/phase-2-trustworthy-context.md)
for routing, semantic governance, freshness, planning and promotion boundaries.

The staged [development roadmap](docs/development-roadmap.md) defines the
white-goods pilot and later industry-pack factory without coupling the core to
that first pilot.

See the [white-goods lab](reference_labs/white_goods/README.md) for its mock
data, representative technology topology, GQM scorecard, and explicit runtime
evidence boundary.
