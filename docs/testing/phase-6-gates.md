# Phase-6 verification gates

Run the complete chain with:

```bash
make phase6
```

| Gate | Required evidence |
|---|---|
| Source shapes | PostgreSQL, S3, event-stream and REST fixture contracts execute in workers |
| Isolation | every call is a replaceable child process with exact one-line RPC |
| Timeout/cancel | overdue and canceled children are terminated |
| Crash/oversize | non-zero exit and oversized output fail closed |
| Saturation | observed worker concurrency never exceeds the declared limit |
| Credential boundary | child receives credential references and no inherited sensitive variables |
| MCP profile | per-request metadata, deterministic scoped list, private caching, pinned call and header/body binding pass |
| A2A profile | Agent Card declares `1.0`; one JSON data part maps to a non-executed bounded action |
| ABI isolation | connector core contains zero MCP/A2A/JSON-RPC coupling tokens |
| Evidence separation | four external planes keep contract/CI/publish/deploy/runtime/fault/acceptance states distinct |
| Transfer packet | wheel, schemas, evidence and OpenShift templates verify checksum, signature and SBOM |
| False readiness | unresolved images, mirror, cluster, runtime and stakeholder gates remain false with blockers |
| Regression | Phase 0 through Phase 5 rerun first |

The local profile tests do not claim upstream MCP/A2A conformance. The fixture
workers do not claim live production-source behavior. The signed packet does not
claim mirrored images or a deployed OpenShift runtime. OS-process workers use
host networking; zero-egress evidence begins with the later container/OpenShift
campaign.
