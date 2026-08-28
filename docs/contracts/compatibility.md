# Cross-plane compatibility policy

`compatibility/cross-plane-release-set.lock.json` records the exact upstream revisions used to design and test the contract boundary. A pin proves input identity only. It does not prove that upstream CI, deployed runtime behavior, air-gap behavior or stakeholder acceptance passed.

Compatibility changes require:

1. a new exact upstream revision and version where one exists;
2. review against `contracts/catalog.v1.json` to prevent duplicate ownership;
3. passing schema fixtures and package tests;
4. Phase-1 source, Phase-2 trustworthy-context, Phase-3 pack, Phase-4 action, Phase-5 durable/protocol, Phase-6 worker/profile and Phase-6.5 integration-spine consumer tests in the selected reference labs;
5. an exact historical entry in `phase2-compatibility-matrix.json`; compatible
   changes to a Phase-2 schema must preserve its original digest lock and add
   exact old/new digests plus a reason to `phase2-contract-evolution.json`;
6. separate capture of source, CI, deployment/runtime and stakeholder evidence.

`PromotionReadiness` is a data-plane input. It must never be interpreted as ADLC's authoritative `PromotionDecision`, and contract compatibility must never be promoted to runtime acceptance.

Phase 6 adds `CrossPlaneEvidenceSet`. Its states are intentionally independent:
contract or CI success cannot set publication, deployment, runtime, fault or
stakeholder acceptance. The historical Phase-2 lock remains immutable; the
Phase-6 evidence set carries the newer exact integration inputs.

Phase 6.5 requires exactly the four named platform planes and makes the current
evidence revisions equal the current release-set lock. Harness-side seam tests
can pass only the `contract` claim; they cannot infer upstream CI, publication,
deployment, runtime, fault or stakeholder states.

Phase 7 readiness adds `LiveAcceptanceCampaign`. It includes the harness beside
the four platform planes and requires an independent observation for every
component/stage pair. Derived `accepted`, blocker and release-set-digest fields
are recomputed when a contract is read. Source or CI evidence may bind a source
revision before publication; publication and every later stage must bind the
same non-null artifact digest. A partial matrix remains a failed campaign even
when some upstream CI is green.

Public SDK telemetry remains tenant-neutral. Industry and product names belong in caller-supplied values or lab manifests, not generic API field names.
