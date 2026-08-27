# Phase-1 verification gates

Run the complete Phase-0 and Phase-1 chain with:

```bash
make phase1
```

The Phase-1 gate validates:

| Area | Required evidence |
|---|---|
| Manifests and topology | strict industry/lab manifests, OpenAPI contract, four-service internal-only Compose topology |
| Connector fidelity | all five connector profiles pass foundation conformance and expected row/relationship checks |
| Determinism | mutation changes the snapshot; reset restores the exact baseline digest |
| Authorization | allowed customer request succeeds; cross-customer request is denied before data emission |
| Provenance | every returned batch/hit has source, asset, version and record lineage |
| Stream behavior | duplicate event removed, late event retained, missing-key event quarantined, replay resumes after checkpoint |
| Semantic correctness | drainage-motor alias joins the drain-pump identity cluster while E21 remains a non-identity mention |
| Retrieval quality | the ten-question suite meets recall-at-3 threshold with role ACL filtering |
| Content safety | adversarial text remains present but explicitly labelled `untrusted-source` |
| Failure handling | injected outage reports unhealthy and fails explicitly |
| Performance | p95 of 100 bounded local queries remains within the GQM budget |
| Air-gap behavior | full scenario runs with socket connection disabled and external egress is denied |

The report preserves the evidence boundary: application-level certification is distinct from image mirroring, deployed OpenShift network policy, upstream plane CI and stakeholder acceptance. Accuracy and retrieval scores apply only to the version-locked synthetic lab corpus; production generalization requires a separately governed, unseen evaluation set.
