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

**Exit:** a second industry pack uses compatible, evidence-tracked core
contracts and demonstrates that no white-goods assumptions leaked into public
APIs.

**Repository exit:** the deterministic generator reproduces every committed
cold-chain fixture with valid relationships; the OpenAPI scaffold is contract
valid and compilable; the disconnected connector archive verifies its checksum,
signature and complete SBOM; wrong signer identities are refused; and the 14
Phase-2 schema digests remain immutable in their baseline lock. Later compatible
changes require exact old/new digests and a reason in the evolution ledger.

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

## Phase 6 — production-shaped runtime scaffold and acceptance packet

**Implementation status:** the repository-scoped runtime scaffold is implemented
in core version `0.7.0`. Completion is revision-specific: `make phase6`, Python
3.11/3.12 CI and CodeQL must be green for the referenced revision. The
combined-platform/live-source campaign is not complete and remains Phase 7.

- production-shape PostgreSQL, S3-compatible, event-stream and REST contracts
  execute behind replaceable OS-process workers while preserving the connector
  ABI;
- worker deadlines, cancellation, crash replacement, response-size bounds,
  parallelism and credential-reference-only environment handling are certified;
- the northbound adapter is exposed through version-pinned MCP `2026-07-28`
  tools and A2A `1.0` SendMessage profiles without leaking either protocol into
  the connector core;
- integrate SDK telemetry/receipts, ADLC evidence and promotion inputs,
  model-plane embedding/reranking and OCP deployment ownership through a
  revision-pinned cross-plane evidence set;
- produce a signed deterministic air-gap transfer packet with OpenShift
  deployment/security templates and an explicit readiness record.

**Repository exit:** four representative source shapes run through the worker
boundary; timeout, crash, oversize-response and cancellation faults fail closed;
MCP/A2A local profile checks pass; protocol vocabulary remains outside the
connector ABI; the transfer packet verifies its checksum, signature and SBOM;
and external-plane contract, CI, publication, deployment, runtime, fault and
stakeholder evidence remain separately represented.

**Evidence boundary:** the sources are deterministic production-shape fixtures,
not live PostgreSQL/S3/Kafka/REST services. The MCP/A2A checks are local
specification profiles, not their upstream conformance suites. The transfer
packet is not mirrored, deployed or accepted; unresolved image digests and live
runtime gates remain blockers. Process workers use host networking and do not
claim container or zero-egress isolation.

## Phase 6.5 — repository integration spine and hardened trust boundaries

**Implementation status:** implemented in core version `0.8.0`. Completion is
revision-specific: `make phase6.5`, Python 3.11/3.12 CI and CodeQL must be green
for the referenced revision. Live-source and combined-platform acceptance remain
Phase 7.

- execute bounded multi-asset plans end to end through policy, gateway and the
  white-goods pilot connector;
- expose a canonical `WorkerBackedConnector` so gateway calls cross the same
  process boundary certified in Phase 6;
- coordinate independent query/search steps concurrently with an explicit
  expected-source universe, failure exclusions and deduplicated lineage;
- enforce gateway deadlines, per-connector parallelism, aggregate result-size,
  finite-JSON, source-version, search-ACL and source-identity invariants;
- require a pluggable cryptographic approval verifier and keyed durable-journal
  integrity instead of trusting human-looking identifiers or an unkeyed chain;
- bound JSON/JSONL/CSV/HTML/text decoding and archive extraction; emit a
  CycloneDX dependency graph for all pinned runtime wheels;
- publish redacted, tenant-neutral execution evidence through Python-SDK and
  ADLC ownership seams, and validate bounded tenant-bound model-plane reranking;
- package an offline wheelhouse recipe, runtime container, lifecycle endpoint,
  OpenShift configuration/service/probes/network policies and `oc-mirror` v2
  input while leaving unresolved image and live-cluster gates false.

**Repository exit:** the planner, four-source pilot and subprocess worker path
all execute; forged approvals, malformed delegations and spoofed container
claims fail closed; the evidence schema requires exactly ADLC, Python-SDK,
OCP-reference-lab and model-plane; the current evidence revisions equal the
release-set lock; the signed transfer packet contains the declared offline and
OpenShift assets; and the Phase 0–6 regression chain remains green.

**Evidence boundary:** this phase proves deterministic fixtures, local process
execution and interface seams. It does not run upstream repository CI or
protocol suites, real PostgreSQL/S3/Kafka/REST services, an approved image build
and scan, registry mirroring, live OpenShift deployment, runtime zero-egress or
fault drills, production generalization, or stakeholder acceptance.

## Phase 7 — live combined-platform and disconnected-runtime acceptance

**Status:** readiness ledger implemented in core version `0.9.0`; live campaign
not complete and no completion claim.

Implemented readiness foundation:

- define a `LiveAcceptanceCampaign` over the harness, ADLC, Python-SDK,
  OCP-reference-lab and model-plane with exact source revisions and nullable
  artifact digests;
- require four unique credential-reference-only targets for PostgreSQL,
  S3-compatible storage, Kafka-compatible streaming and REST;
- preserve an independent source, PR-CI, exact-main-CI, publication, mirror,
  deployment, runtime, fault, soak, protocol-conformance and stakeholder state
  for each platform component;
- recompute the release-set digest, blockers and final acceptance so forged
  derived fields fail closed;
- record the initial read-only evidence snapshot: exact source identity for all
  five components and exact-main CI for the harness, ADLC, OCP reference lab and
  model plane; Python-SDK CI and all later lifecycle stages remain missing;
- record `provisioningAuthorized: false`, zero resources created and zero
  external mutations, keeping readiness work non-billable.

Remaining live campaign:

- replace each fixture transport with a digest-pinned connector image against
  live PostgreSQL, S3-compatible object storage, Kafka-compatible streaming and
  REST services;
- run upstream MCP/A2A conformance tools against the tenant runtime host and
  preserve exact suite versions/results;
- verify Python-SDK receipts/telemetry, ADLC evidence ingestion and promotion
  inputs, model-plane embedding/reranking and OCP deployment overlays at one
  pinned cross-plane release set;
- mirror images and signatures with the supported disconnected OpenShift flow,
  deploy to a live cluster, deny public egress and execute dependency, restart,
  node-loss and recovery drills;
- capture soak/SLO results and named stakeholder acceptance separately.

**Exit:** source, PR CI, exact-main CI, publication, mirror, deployment,
runtime, fault, soak, protocol-conformance and stakeholder states all pass for
the same revisions and artifact digests. Local process/container evidence cannot
substitute for this campaign.
