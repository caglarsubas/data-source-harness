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

**Outcome:** turn the Phase-1 source abstraction into a governed context plane that answers only when mappings, freshness, authorization, coverage and provenance are sufficient.

**Implementation status:** implemented in core version `0.3.0` and white-goods pack `1.1.0`. Completion is revision-specific: `make phase2`, Python 3.11/3.12 CI and CodeQL must be green for the referenced revision.

- semantic-aware source routing and hybrid retrieval;
- human-governed mapping candidates and drift detection;
- resumable CDC/freshness SLOs and richer source families;
- field/relationship authorization and bounded query planning;
- reference-lab promotion workflow and compatibility matrix.

**Repository exit:** covered questions meet the declared GQM routing and provenance thresholds; ambiguous or stale requests refuse/escalate; schema drift quarantines affected mappings; checkpoint regression and unauthorized fields/relationships are denied; every answer exposes complete coverage and exact record provenance; and the Phase-1 certificate remains green.

**Combined-platform acceptance:** the repository emits contract-pinned compatibility and promotion-readiness evidence, but ADLC retains the authoritative `PromotionDecision`. Live SDK workflow execution, model-plane reranking, OCP deployment/runtime evidence and stakeholder approval remain separately required states.

## Phase 3 — reusable industry/domain pack factory

**Implementation status:** implemented in core version `0.4.0` with the
cold-chain excursion-response pack `1.0.0`. Completion is revision-specific:
`make phase3`, Python 3.11/3.12 CI and CodeQL must be green for the referenced
revision.

- versioned `IndustryDomainPackManifest` and reusable mock-data generators;
- additional pilots selected by capability diversity and buyer value;
- automated connector scaffolding from OpenAPI/schema metadata;
- signed connector packages, SBOMs and certification evidence.

**Exit:** a second industry pack uses the unchanged core contracts and demonstrates that no white-goods assumptions leaked into public APIs.

**Repository exit:** the deterministic generator reproduces every committed
cold-chain fixture with valid relationships; the OpenAPI scaffold is contract
valid and compilable; the disconnected connector archive verifies its checksum,
signature and complete SBOM; wrong signer identities are refused; and all 14
Phase-2 schema digests remain exact.

**Evidence boundary:** HMAC signing is a replaceable offline lab verifier, not
production publisher identity. Production connectivity, asymmetric/HSM-backed
signing, deployed runtime proof and stakeholder acceptance remain separate.

## Phase 4 — governed actions and adaptive semantics

**Implementation status:** implemented in core version `0.5.0` and certified
against the white-goods and cold-chain synthetic labs. Completion is
revision-specific: `make phase4`, Python 3.11/3.12 CI and CodeQL must be green
for the referenced revision.

- previewable, idempotent and conditionally authorized source actions;
- approval and compensation workflows;
- governed shared memory promotion and cross-agent semantics;
- A2A-facing delegation adapters without coupling the connector ABI to A2A or MCP.

**Exit:** action safety, rollback/compensation, policy and audit thresholds pass in at least two independent industry labs.

**Repository exit:** every source mutation is preview-bound, conditionally
authorized again at execution, idempotency-keyed and postcondition-checked;
high-risk actions require a digest-bound human approval; declared compensation
restores both lab states; audits are hash-chained and exclude raw mutation
values; semantic candidates require human review before scoped cross-agent
promotion; and over-broad delegation envelopes are rejected before reaching the
connector registry.

**Evidence boundary:** the in-memory labs prove deterministic application
semantics, not durable crash recovery, production connector behavior, live A2A
interoperability, deployed runtime evidence or stakeholder acceptance.

## Phase 5 — durable recovery and protocol-edge certification

**Implementation status:** implemented in core version `0.6.0` and certified
against the white-goods and cold-chain synthetic labs. Completion is
revision-specific: `make phase5`, Python 3.11/3.12 CI and CodeQL must be green
for the referenced revision.

- SQLite write-ahead action records with `FULL` synchronization, WAL mode and a
  metadata-only SHA-256 journal chain;
- a fail-closed uncertain-outcome state that forbids automatic replay after a
  dispatched mutation;
- restart reconciliation against source-owned idempotency/postcondition
  evidence, producing a durable recovered receipt without a second source
  effect;
- a stateless, versioned JSON-RPC `tools/list` and `tools/call` boundary that
  exposes only agent-scoped tools and pins calls to the exact tool-catalog
  digest;
- two-lab crash-window, tool-poisoning, payload-privacy and zero-egress GQM
  certification.

**Repository exit:** both labs persist the uncertain action across a journal
reopen, reject blind execution retry, reconcile to a successful receipt and
retain exactly one source effect; durable journal chains validate and contain no
raw mutation values; unauthorized tool discovery returns no tools; changed tool
metadata invalidates the caller's pin; and protocol vocabulary remains outside
the connector ABI.

**Evidence boundary:** this phase proves a single-node local durable reference
implementation and an internal protocol adapter shape. It does not prove abrupt
OS/power-loss behavior, multi-replica coordination, production database HA,
official MCP/A2A conformance, live OpenShift execution or stakeholder
acceptance.

## Phase 6 — production-source and combined-platform reference runtime

**Status:** planned; no completion claim.

- replace lab mutation sources with containerized, production-representative
  PostgreSQL, S3-compatible, event-stream and REST connector workers while
  preserving the connector ABI;
- certify process isolation, cancellation, saturation, credential references,
  schema upgrades and source-specific idempotency/reconciliation under fault;
- host the northbound adapter behind officially versioned MCP/A2A adapters and
  run their upstream conformance suites without leaking those protocols into the
  connector core;
- integrate SDK telemetry/receipts, ADLC evidence and promotion inputs,
  model-plane embedding/reranking and the OCP reference-lab deployment overlay;
- execute the white-goods reference runtime in disconnected/air-gapped mode
  from a mirrored, signed artifact set.

**Exit:** source, pull-request CI, exact-main CI, signed supply chain,
deployed-runtime behavior, protocol conformance and stakeholder acceptance are
captured as separate evidence states. A local container or mock certificate
cannot substitute for live OpenShift and production-source certification.
