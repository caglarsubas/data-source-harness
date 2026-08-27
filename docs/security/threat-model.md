# Phase-0 threat model

| Threat | Phase-0 control | Required later proof |
|---|---|---|
| Cross-tenant or over-broad reads | required execution identity, local policy seam, capability check before invocation | row/field negative tests in a real connector |
| Credential leakage | contracts accept credential references only; telemetry rejects credential-like fields | secret scanning and runtime log inspection |
| Prompt injection in source content | decoder output is always labelled `untrusted-source` | adversarial document retrieval suite |
| SSRF or accidental internet egress | explicit egress allow-list; air-gap profile disables DNS/external telemetry | network-denied OCP execution evidence |
| Unbounded query/resource use | positive query limit/deadline and connector result/parallelism limits | cancellation, timeout and saturation tests |
| Unsupported or unsafe mutation | read/mutation capabilities are separate; preview, execute-time policy, human approval, conditional writes, idempotency and compensation are certified in two synthetic labs | durable crash recovery and production-source action certification |
| Silent partial answers | required lineage/version data and explicit coverage/exclusions | answer-level coverage and refusal evaluation |
| Incorrect entity merge | append-only assertions, explicit contradictions and redirects | steward workflow and semantic benchmark |
| Connector compromise/failure | process/container runtime modes are declared | worker isolation, replacement and supply-chain certification |
| Control-plane outage | no synchronous ADLC call in the execution gateway | disconnected control-plane failure injection |
| Stale source evidence | per-asset freshness observations, watermarks and breach action | live-source SLO calibration and alerting |
| Semantic schema drift | approved mappings are digest-bound and quarantined on change | steward review against production schema changes |
| Ambiguous source mapping | equal plausible mappings escalate without answer content | unseen production ambiguity/refusal benchmark |
| Unauthorized join or field inference | bounded planner plus gateway field/relationship re-authorization | real connector query-plan inspection |
| Evidence-state collapse | source, CI, runtime and stakeholder states remain distinct; ADLC owns promotion | combined-platform promotion campaign |

Phase 0 defines and unit-tests the enforcement seams. It does not claim that a deployment, connector image or upstream product is certified against every threat.

Phase 4 closes the original application-level mutation proof gap in the two
synthetic reference labs. It does not close production connector, durable
workflow, deployment or stakeholder evidence gaps.
