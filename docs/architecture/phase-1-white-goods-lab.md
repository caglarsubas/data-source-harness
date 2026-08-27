# Phase 1 architecture: white-goods reference lab

Phase 1 proves that the Phase-0 contracts can support heterogeneous industry data without changing the public connector, policy, lineage, semantic, coverage or deployment abstractions.

## Lab data flow

1. `whitegoods.erp` discovers and queries installed-base, service and quality records through bounded field/equals plans—never generated raw SQL.
2. `whitegoods.documents` preserves object identity, content hash, role ACL and the `untrusted-source` label with each technical document.
3. `whitegoods.telemetry` exposes deterministic at-least-once events, event-id deduplication, late-event marking, missing-key quarantine and sequence checkpoints.
4. `whitegoods.service-api` models a rate-limited, paginated OpenAPI service-management boundary.
5. `whitegoods.search` performs deterministic hybrid-style fusion over the document corpus while preserving ACL decisions and source lineage.
6. `HarnessGateway` performs capability negotiation and local policy authorization before connector execution and emits tenant-neutral evidence events asynchronously.

## ADLC platform composition

The lab emits the artifacts that the existing product planes can consume without reimplementing them:

- ADLC receives certification metrics, telemetry and evidence asynchronously for promotion decisions.
- Orchestra Python SDK remains the signed workflow/MCP execution boundary; the lab calls the harness through its neutral Python contracts.
- The model plane can replace deterministic synonym scoring with approved local embeddings/reranking without changing the `SearchRequest`/`SearchHit` contract.
- The OCP reference lab can deploy the topology using customer-mirrored images and collect cluster evidence separately from this repository’s application-level certificate.

## Security boundary

The service agents are scoped to their assigned synthetic customer; the quality agent receives aggregate/source access without a customer grant. A cross-customer request is rejected before a batch is emitted. Document ACL filtering is enforced both by policy attributes and the retrieval connector. Source text—including an explicit prompt-injection sample—remains untrusted evidence.

The certification suite replaces socket `connect` during the complete zero-egress scenario and requires zero attempts. This proves that the deterministic application path has no network dependency. It is not evidence that an external Kubernetes or OpenShift network policy was deployed.
