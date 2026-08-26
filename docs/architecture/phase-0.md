# Phase 0 architecture: governed data-context scaffold

Phase 0 establishes a source-neutral, tenant-local data context and execution layer. It deliberately does not select an industry, copy mature control-plane capabilities, or claim a certified combined deployment.

## Plane boundaries

| Plane | Responsibility | Synchronous request-path dependency |
|---|---|---|
| ADLC | solution composition, governance, evaluation, promotion and evidence | No |
| Python SDK | signed agent execution, MCP brokering, receipts and tenant-neutral telemetry | Optional adapter only |
| Data-source harness | discovery, description, retrieval, source authorization, lineage, coverage and semantic assertions | Yes; this repository |
| Model plane | chat, embedding, reranking, structured output and guardrails | Optional, policy-approved local endpoint |
| OCP reference lab | deployment overlays and certification evidence | No; deployment target |

The data path fails locally if its policy evaluator, connector capability, lineage, or deployment egress checks fail. An ADLC outage must not turn into an implicit data authorization bypass or a synchronous production-data outage.

## Public contracts

`contracts/catalog.v1.json` is the ownership ledger. Existing ADLC, SDK, model-plane and OCP contracts remain owned upstream. This repository owns only connector profiles, data batches, semantic assertions, entity redirects, coverage statements, checkpoint tokens, deployment profiles, reference-lab manifests and industry/domain-pack manifests. All owned wire contracts use strict JSON Schema and carry explicit schema versions.

The Python API mirrors those invariants:

- capability negotiation precedes connector invocation;
- authorization is local, purpose-aware and default-deny capable;
- every `DataBatch` carries source versions and field/record lineage;
- semantic links are append-only assertions, never destructive entity rewrites;
- coverage explicitly reports omitted or incomplete sources;
- telemetry uses the tenant-neutral `data.harness.*` namespace and excludes secrets;
- air-gapped egress is explicit allow-list only.

## Execution flow

1. A signed execution supplies organization, solution, agent, request, trace and policy identities.
2. The gateway resolves a connector and verifies the requested capability.
3. A local policy evaluator decides access for the stated purpose and assets.
4. The connector returns versioned, lineage-bearing batches.
5. Coverage and telemetry become evidence inputs for ADLC asynchronously.
6. Optional model-plane calls are permitted only through the deployment egress profile.

## Phase-0 completion definition

Phase 0 is complete when package linting, unit tests, strict schema positive/negative fixtures, the machine-readable artifact gate and wheel construction pass in supported Python versions. Cross-repository revisions are pinned as compatibility inputs. Full multi-plane runtime certification and industry-specific datasets begin in Phase 1 and must not be represented as Phase-0 proof.

## Non-goals

- production connectors or credential stores;
- white-goods ontology, mock data or scenarios;
- a replacement for ADLC, Orchestra SDK, the model plane or OpenShift lab;
- live cross-plane or OpenShift certification;
- autonomous mutation of source systems.
