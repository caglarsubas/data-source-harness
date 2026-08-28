# Phase 7 readiness verification gates

Run the complete local chain with:

```bash
make phase7-readiness
```

The target reruns Phases 0 through 6.5, validates the installed wheel and then
certifies that:

- the campaign schema has positive and false-acceptance fixtures;
- the parser recomputes the release-set digest, blocker list and acceptance;
- exactly five revision-pinned platform components and four live source shapes
  are represented;
- publication and later evidence cannot omit an artifact digest;
- endpoints remain credential references;
- the snapshot equals its deterministic source/CI observations;
- Python-SDK CI, artifact publication, image resolution, live services,
  protocol, mirror, deployment, runtime, fault, soak and stakeholder evidence
  remain blockers;
- provisioning is unauthorized and certification creates no resources or
  external mutations.

A passing readiness report means the evidence machinery is ready to receive
live results. Its `campaign_accepted` field must remain false until the external
campaign actually closes every gate.
