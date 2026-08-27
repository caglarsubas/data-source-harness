# Phase 6.5 verification gates

Run the complete repository chain with:

```bash
make phase6.5
```

The gate reruns Phases 0–6, builds the core wheel and a pinned Linux wheelhouse,
then certifies:

- bounded E21 planner output through policy, gateway and two pilot assets;
- complete four-source coverage and record lineage;
- canonical gateway-to-subprocess connector execution;
- rejection of forged approvals, cross-request approvals, malformed A2A
  compensation and process workers that claim container-image evidence;
- tenant-neutral Python-SDK receipt, ADLC evidence and model-plane rerank seams;
- exact equality between the four-plane release lock and evidence set;
- signed bundle integrity, dependency SBOM graph and presence of the container,
  mirror and OpenShift assets;
- truthful false values and blockers for every unobserved live-runtime state.

CI additionally enforces branch coverage of at least 85 percent on the core
package and validates the installed wheel without the repository or development
extras. Phase 7 remains responsible for upstream CI/protocol evidence, live
services, approved images, mirroring, OpenShift runtime/fault/zero-egress proof
and stakeholder acceptance.
