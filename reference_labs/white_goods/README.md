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

The optional `docker-compose.yml` documents the heterogeneous deployment topology on an internal-only network. The certification path is deliberately offline and does not pull or start those images. Air-gapped deployments must first replace every development image tag with an approved mirrored digest recorded outside source control.

## Data characteristics

The mock corpus includes repeat visits, product/serial/customer relationships, manufacturing lots, failures, technical guidance, role ACLs, a duplicate event, a late event, a missing-key quarantine event and adversarial document text. All identities are synthetic.

## Run

```bash
make phase1
```

The generated `phase1-report.json` contains every GQM threshold, observed value and evidence note. It certifies deterministic application-level behavior and zero socket egress. Its perfect scores describe the bounded synthetic corpus and are not evidence of production generalization. It does not claim that a live OpenShift cluster or mirrored container estate was deployed.
