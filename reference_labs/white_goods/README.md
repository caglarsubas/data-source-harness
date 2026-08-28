# White-goods service and quality reference lab

This lab is the first industry consumer of the neutral data-source harness. It models an installed-product/service/quality workflow without placing white-goods names or fields in the public core API.

## Representative source estate

| Source | Production analogue | Deterministic certification adapter |
|---|---|---|
| ERP and quality tables | PostgreSQL | bounded CSV-backed tabular connector plus PostgreSQL DDL |
| Technical documents | S3-compatible MinIO | local immutable Markdown objects with ACL and content hashes |
| Product telemetry | Kafka-compatible Redpanda | ordered JSONL with checkpoint, duplicate, late and quarantined events |
| Service scheduling | REST/OpenAPI | OpenAPI 3.1 contract plus paginated response fixtures |
| Hybrid retrieval | OpenSearch | deterministic lexical/semantic synonym fusion with ACL filtering |
| Governed semantics | Property graph | lineage-bound assertions and steward-approved mapping candidates |

The optional `docker-compose.yml` documents the heterogeneous laptop topology
on an internal-only network. The certification path is deliberately offline.
Phase 7 uses `live/compose.template.yaml`, requires images to be preloaded by
digest and never pulls them implicitly.

## Data characteristics

The mock corpus includes repeat visits, product/serial/customer relationships, manufacturing lots, failures, technical guidance, role ACLs, a duplicate event, a late event, a missing-key quarantine event and adversarial document text. All identities are synthetic.

## Run

```bash
make phase7-local-readiness
```

`phase1-report.json` retains the source and zero-egress certificate. `phase2-report.json` adds ten GQM metrics for approved/fresh routing, exact provenance, ambiguity and stale refusal, drift quarantine, bounded planning, monotonic checkpoints, compatibility pins and promotion evidence separation.

The perfect scores describe the bounded synthetic corpus and are not evidence
of production generalization or a completed combined ADLC/SDK/model-plane
runtime. ADLC retains the final promotion decision.

Phase 6 adds replaceable process workers for the four primary source shapes,
version-pinned MCP/A2A action profiles and a signed runtime transfer packet. Its
readiness record intentionally remained blocked on immutable image and runtime
evidence. Its OpenShift assets are historical and no longer a roadmap target.

Phase 6.5 executes the bounded E21 plan and four-source brief through reusable
gateway/coordinator paths, exercises the canonical connector ABI through the
subprocess worker and adds the pinned wheelhouse. The historical OpenShift
handoff is retained for traceability but is not executed.

Phase 7 local readiness uses `live/compose.template.yaml`, which covers PostgreSQL,
S3-compatible storage, Kafka-compatible streaming and REST without mutable
image defaults, embedded secrets, published host ports or implicit startup.
`pull_policy: never` requires approved images to exist on the laptop. The
acceptance ledger remains false until local evidence is produced; it cannot
authorize GCP, OpenShift or remote-cluster resources.
