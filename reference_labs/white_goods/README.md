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

The optional `docker-compose.yml` documents the heterogeneous deployment topology on an internal-only network. The certification path is deliberately offline and does not pull or start those images. Air-gapped deployments must first replace every development image tag with an approved mirrored digest recorded outside source control.

## Data characteristics

The mock corpus includes repeat visits, product/serial/customer relationships, manufacturing lots, failures, technical guidance, role ACLs, a duplicate event, a late event, a missing-key quarantine event and adversarial document text. All identities are synthetic.

## Run

```bash
make phase6.5
```

`phase1-report.json` retains the source and zero-egress certificate. `phase2-report.json` adds ten GQM metrics for approved/fresh routing, exact provenance, ambiguity and stale refusal, drift quarantine, bounded planning, monotonic checkpoints, compatibility pins and promotion evidence separation.

The perfect scores describe the bounded synthetic corpus and are not evidence of production generalization. They do not claim that a live OpenShift cluster, mirrored container estate or combined ADLC/SDK/model-plane runtime was deployed. ADLC retains the final promotion decision.

Phase 6 adds replaceable process workers for the four primary source shapes,
version-pinned MCP/A2A action profiles and a signed runtime transfer packet. Its
readiness record intentionally remains blocked on immutable image digests,
signature mirroring, live OpenShift deployment, runtime fault evidence and
stakeholder acceptance.

Phase 6.5 executes the bounded E21 plan and four-source brief through reusable
gateway/coordinator paths, exercises the canonical connector ABI through the
subprocess worker, and adds the pinned wheelhouse and OpenShift runtime handoff.
The certificate still treats every live-source, image, mirror, cluster and
stakeholder state as separate evidence.
