# Solution development roadmap

This roadmap builds an industry-neutral data-source harness first, then proves it with realistic industry reference labs. Each phase advances only through measurable evidence; source state, CI, deployed runtime and stakeholder acceptance are recorded separately.

## Phase 0 — reusable foundation

**Outcome:** a distributable Python scaffold with stable ownership boundaries and executable safety invariants.

- connector discovery, capability negotiation and canonical lineage-bearing data objects;
- untrusted-content decoder boundary;
- local authorization and tenant-neutral telemetry seams;
- semantic assertions, entity redirects, checkpoints and coverage contracts;
- connected, self-hosted and fail-closed air-gapped profiles;
- strict JSON Schemas with passing and failing fixtures;
- connector conformance API, upstream compatibility lock and automated CI/CodeQL gates.

**Exit:** `make phase0` passes on Python 3.11 and 3.12, the package builds, and the merge revision is green. This certifies the scaffold only, not a combined deployed platform.

## Phase 1 — white-goods reference lab

**Outcome:** prove the abstraction with representative, legally safe mock data and heterogeneous technologies.

**Implementation status:** implemented as the `white-goods-service-quality` industry pack. Completion is revision-specific: `make phase1`, Python 3.11/3.12 CI and CodeQL must be green for the referenced revision.

Use a service-and-quality scenario spanning an ERP-style PostgreSQL database, a product/document S3-compatible store, a manufacturing/event stream, a service-management REST API and hybrid search. Build deterministic reset/seed tooling and intentionally include late events, duplicates, missing keys, conflicting identifiers, stale documents, ACL boundaries, schema evolution and outages.

Apply Goal–Question–Metric design to every scenario. Example: goal “reduce repeat service visits”; questions test whether the system can identify failure patterns without crossing tenant or customer permissions; metrics include grounded answer accuracy, citation/lineage completeness, refusal precision, p95 latency, replay correctness and zero-egress violations.

**Repository exit:** the published lab pack passes connector fidelity, authorization, failure-injection, replay, semantic, retrieval-quality, performance and zero-egress suites, and its deterministic offline bundle verifies against its embedded checksum manifest.

**Combined-platform acceptance:** ADLC evidence ingestion, Orchestra SDK workflow execution, local model-plane embeddings/reranking and OCP deployment verification are a separate cross-plane campaign against the pinned release set. They are target consumers of the Phase-1 artifacts, not evidence this repository can manufacture or silently infer. Image mirroring, live-cluster policy enforcement, upstream CI and stakeholder acceptance remain distinct release states.

## Phase 2 — trustworthy cross-source context

- semantic-aware source routing and hybrid retrieval;
- human-governed mapping candidates and drift detection;
- resumable CDC/freshness SLOs and richer source families;
- field/relationship authorization and bounded query planning;
- reference-lab promotion workflow and compatibility matrix.

**Exit:** covered questions meet agreed accuracy and citation thresholds, ambiguous requests refuse or escalate, and every answer exposes coverage and exact provenance.

## Phase 3 — reusable industry/domain pack factory

- versioned `IndustryDomainPackManifest` and reusable mock-data generators;
- additional pilots selected by capability diversity and buyer value;
- automated connector scaffolding from OpenAPI/schema metadata;
- signed connector packages, SBOMs and certification evidence.

**Exit:** a second industry pack uses the unchanged core contracts and demonstrates that no white-goods assumptions leaked into public APIs.

## Phase 4 — governed actions and adaptive semantics

- previewable, idempotent and conditionally authorized source actions;
- approval and compensation workflows;
- governed shared memory promotion and cross-agent semantics;
- A2A-facing delegation adapters without coupling the connector ABI to A2A or MCP.

**Exit:** action safety, rollback/compensation, policy and audit thresholds pass in at least two independent industry labs.
