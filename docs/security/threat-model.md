# Phase-0 threat model

| Threat | Phase-0 control | Required later proof |
|---|---|---|
| Cross-tenant or over-broad reads | required execution identity, local policy seam, capability check before invocation | row/field negative tests in a real connector |
| Credential leakage | contracts accept credential references only; telemetry rejects credential-like fields | secret scanning and runtime log inspection |
| Prompt injection in source content | decoder output is always labelled `untrusted-source` | adversarial document retrieval suite |
| SSRF or accidental internet egress | explicit egress allow-list; laptop-local profile permits only service aliases and loopback and disables external telemetry | laptop container-network denial evidence |
| Unbounded query/resource use | positive query limit/deadline and connector result/parallelism limits | cancellation, timeout and saturation tests |
| Unsupported or unsafe mutation | read/mutation capabilities are separate; preview, execute-time policy, cryptographically verified human approval, conditional writes, idempotency, compensation and local durable reconciliation are certified in two synthetic labs | production ADLC approval authority, source action and multi-replica runtime certification |
| Unknown mutation outcome | keyed-integrity write-ahead durable state; automatic replay is forbidden; source idempotency/postcondition reconciliation is mandatory | external key custody, abrupt power-loss and production-source reconciliation campaign |
| Tool metadata poisoning | immutable catalog digest, agent-scoped listing and digest-pinned calls | official MCP/A2A host conformance and signed remote catalog distribution |
| Connector worker escape or resource abuse | no shell, replaceable child process, bounded bytes/deadline/parallelism, cancellation kill and sanitized environment | container/seccomp/SELinux isolation and live saturation proof |
| Protocol-version confusion | explicit MCP/A2A versions, per-request metadata, header/body binding and strict envelopes | upstream conformance suites and authenticated live transports |
| Evidence-state collapse across planes | typed contract/CI/publish/deploy/runtime/fault/stakeholder claims; missing evidence cannot be promoted | combined release-set acceptance campaign |
| Silent partial answers | required lineage/version data, expected-source universe and explicit coverage/exclusions | answer-level coverage and refusal evaluation |
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

Phase 5 closes deterministic single-node gateway-restart recovery and local
tool-catalog poisoning gaps. Production connector workers, abrupt host failure,
multi-replica coordination, official protocol hosting, OpenShift runtime and
stakeholder acceptance remain open evidence states.

Phase 6 closes the local connector-process and cross-plane evidence-model gaps.
It does not close container isolation, real source connectivity, upstream
protocol conformance, image mirroring, live OpenShift, dependency faults, soak or
stakeholder acceptance.

Phase 6.5 additionally closes forged human-label approval, unkeyed journal
tamper detection, planner-to-connector integration, silent expected-source
omission and unbounded decoder/archive gaps in the local implementation. It
does not close production key custody, container isolation, real service
connectivity, external-plane authentication or any live deployment gate.

Phase 7 readiness closes the evidence-ledger ambiguity around the local campaign:
four exact component revisions, four local source shapes, artifact digests and
all eleven lifecycle stages have machine-checkable identities and derived
blockers. It prohibits cloud and cluster infrastructure and therefore does not
close local image, service, protocol, runtime, fault, soak or stakeholder gates.
