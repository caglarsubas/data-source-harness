# Phase-0 verification gates

The local and CI command is:

```bash
make phase0
```

It must pass these independent gates:

| Gate | Evidence | Failure meaning |
|---|---|---|
| Static quality | `ruff check` and `ruff format --check` | package is not releasable |
| Behavioral tests | `pytest` | Python invariants or gateway behavior failed |
| Contract fixtures | positive fixtures accepted and negative fixtures rejected | wire contract is missing or permissive |
| Artifact gate | `phase0-report.json` with `passed: true` | required contract, deployment or architecture artifact is absent |
| Package build | wheel and sdist created | scaffold cannot be distributed offline |

CI runs on Python 3.11 and 3.12. The Phase-0 report is a scaffold acceptance artifact, not multi-plane runtime certification. Phase 1 adds reference-lab tests for deterministic reset, data fidelity, authorization, failure injection, replay/checkpoint behavior, semantic correctness, retrieval quality, throughput and zero-egress operation.

Air-gap acceptance must run with network egress denied, dependencies and images sourced from an internal mirror, external telemetry disabled, and local model endpoints explicitly allow-listed. A configuration file alone is not air-gap runtime proof.
