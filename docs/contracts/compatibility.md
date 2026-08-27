# Cross-plane compatibility policy

`compatibility/cross-plane-release-set.lock.json` records the exact upstream revisions used to design and test the contract boundary. A pin proves input identity only. It does not prove that upstream CI, deployed runtime behavior, air-gap behavior or stakeholder acceptance passed.

Compatibility changes require:

1. a new exact upstream revision and version where one exists;
2. review against `contracts/catalog.v1.json` to prevent duplicate ownership;
3. passing schema fixtures and package tests;
4. Phase-1 source and Phase-2 trustworthy-context consumer tests in the selected reference lab;
5. an exact entry in `phase2-compatibility-matrix.json` with contract-only evidence;
6. separate capture of source, CI, deployment/runtime and stakeholder evidence.

`PromotionReadiness` is a data-plane input. It must never be interpreted as ADLC's authoritative `PromotionDecision`, and contract compatibility must never be promoted to runtime acceptance.

Public SDK telemetry remains tenant-neutral. Industry and product names belong in caller-supplied values or lab manifests, not generic API field names.
