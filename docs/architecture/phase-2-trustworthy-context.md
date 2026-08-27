# Phase 2 architecture: trustworthy cross-source context

Phase 2 adds governance and execution constraints around the Phase-1 connectors without embedding white-goods concepts in the public core.

## Decision flow

1. Automation may propose a lineage-bound `SemanticMappingCandidate`; only an explicit `human:*` steward identity can approve or reject it.
2. A schema-digest change quarantines an approved mapping. It is never silently rewritten or kept routable.
3. `SemanticSourceRouter` considers only approved, non-quarantined mappings that meet the request's confidence and freshness SLO.
4. Equally plausible cross-source mappings produce `escalation_required`; missing, stale or over-broad routes produce `refused`.
5. `BoundedQueryPlanner` checks assets, asset-qualified filters, fields, relationships, row limits and deadlines before producing a connector request. `FieldRelationshipPolicy` rechecks the emitted shape against an organization/solution/agent-scoped grant before execution.
6. An answer is valid only when its route and coverage are complete and exact record-level lineage is present.
7. Checkpoint positions and connector versions advance monotonically; version changes require an explicit migration.

## Reference-lab expansion

The white-goods pack adds a governed semantic-graph connector to the existing tabular, document, event, REST and search families. Its covered E21 scenario routes four concepts through four fresh sources and returns seven exact source records. Ambiguous component mappings and stale evidence are exercised as non-answer paths.

## Promotion ownership

This repository owns `PromotionReadiness`, not `PromotionDecision`. Source, CI, deployed runtime and stakeholder evidence remain separate inputs. The compatibility matrix proves exact contract pins only; it does not manufacture live combined-platform evidence for ADLC, the SDK, model plane or OpenShift lab.

All Phase-2 certification remains deterministic and network-independent, preserving the air-gapped application path established in Phase 1.
