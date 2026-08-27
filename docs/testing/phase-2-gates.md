# Phase-2 verification gates

Run the complete Phase-0 through Phase-2 chain with:

```bash
make phase2
```

The Phase-2 certificate reruns Phase 1 and then validates:

| Area | Required evidence |
|---|---|
| Semantic governance | unreviewed mappings cannot route; only human stewards approve; schema drift quarantines without automatic rewrite |
| Source routing | four covered concepts route through approved, fresh sources within the source bound |
| Ambiguity | equal plausible cross-source mappings escalate without answer content |
| Freshness | selected routes expose watermarks; stale evidence is excluded/refused according to the SLO |
| Source diversity | the semantic graph source passes the connector conformance contract |
| Query safety | unauthorized fields, relationships, row counts and deadlines fail before connector execution |
| CDC | checkpoint resume is monotonic and connector-version changes require migration |
| Grounding | an answer requires complete coverage and exact record-level provenance across all included sources |
| Compatibility | all four mature-plane revisions match the exact pinned contract matrix |
| Promotion | missing runtime or stakeholder evidence keeps readiness false; ADLC retains the final decision |

The ten Phase-2 GQM metrics apply only to the versioned synthetic lab. They do not demonstrate production generalization or live combined-platform acceptance.
