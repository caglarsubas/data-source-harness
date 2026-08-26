# Phase-0 threat model

| Threat | Phase-0 control | Required later proof |
|---|---|---|
| Cross-tenant or over-broad reads | required execution identity, local policy seam, capability check before invocation | row/field negative tests in a real connector |
| Credential leakage | contracts accept credential references only; telemetry rejects credential-like fields | secret scanning and runtime log inspection |
| Prompt injection in source content | decoder output is always labelled `untrusted-source` | adversarial document retrieval suite |
| SSRF or accidental internet egress | explicit egress allow-list; air-gap profile disables DNS/external telemetry | network-denied OCP execution evidence |
| Unbounded query/resource use | positive query limit/deadline and connector result/parallelism limits | cancellation, timeout and saturation tests |
| Unsupported or unsafe mutation | read and mutation capabilities are separate; policy remains mandatory | approval/idempotency tests before writes are enabled |
| Silent partial answers | required lineage/version data and explicit coverage/exclusions | answer-level coverage and refusal evaluation |
| Incorrect entity merge | append-only assertions, explicit contradictions and redirects | steward workflow and semantic benchmark |
| Connector compromise/failure | process/container runtime modes are declared | worker isolation, replacement and supply-chain certification |
| Control-plane outage | no synchronous ADLC call in the execution gateway | disconnected control-plane failure injection |

Phase 0 defines and unit-tests the enforcement seams. It does not claim that a deployment, connector image or upstream product is certified against every threat.
