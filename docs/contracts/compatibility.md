# Cross-plane compatibility policy

`compatibility/cross-plane-release-set.lock.json` records the exact upstream revisions used to design and test the contract boundary. A pin proves input identity only. It does not prove that upstream CI, deployed runtime behavior, air-gap behavior or stakeholder acceptance passed.

Compatibility changes require:

1. a new exact upstream revision and version where one exists;
2. review against `contracts/catalog.v1.json` to prevent duplicate ownership;
3. passing schema fixtures and package tests;
4. Phase-1 consumer tests in the selected reference lab;
5. separate capture of source, CI, deployment and acceptance evidence.

Public SDK telemetry remains tenant-neutral. Industry and product names belong in caller-supplied values or lab manifests, not generic API field names.
