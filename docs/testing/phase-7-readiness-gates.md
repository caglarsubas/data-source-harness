# Phase 7 readiness verification gates

Run the complete local chain with:

```bash
make phase7-local-readiness
```

The target reruns Phases 0 through 6.5, validates the installed wheel and then
certifies that:

- the campaign schema has positive and false-acceptance fixtures;
- the parser recomputes the release-set digest, blocker list and acceptance;
- exactly four revision-pinned locally runnable platform components and four local source shapes
  are represented;
- publication and later evidence cannot omit an artifact digest;
- endpoints remain credential references;
- the snapshot equals its deterministic source/CI observations;
- all four source images are immutable, platform-consistent and bound to an
  observed local runtime packet;
- seeded PostgreSQL query, MinIO listing, Redpanda consumption and REST
  authentication/pagination checks pass;
- Python-SDK CI, platform artifact publication, combined-platform image load
  and startup, protocol, runtime, fault, soak and stakeholder evidence
  remain blockers;
- `pull_policy: never`, no host-published ports and an internal-only Compose
  network prevent implicit pulls and externally exposed services;
- GCP, OpenShift and remote-cluster provisioning are prohibited rather than
  merely awaiting authorization;
- executable workflows and scripts pass the local-only automation scan.

A passing readiness report means the evidence machinery is ready to receive
local results. Its `campaign_accepted` field remains false until the laptop-local
campaign closes every gate for one digest-pinned release set.

`make phase7-local-sources` is the explicit laptop-only evidence refresh. It
requires the three upstream source images to be present locally, builds the REST
mock with `--pull=false`, creates no host ports or external resources, and tears
down its containers and volumes after verification.
