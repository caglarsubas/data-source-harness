# White-goods runtime transfer packet

This directory is the immutable Phase 6/6.5 air-gap transfer scaffold. It binds
the harness wheel, worker/protocol contracts, cross-plane revision set and
historical deployment templates into a deterministic signed archive.

The current roadmap does not deploy these OpenShift templates, run `oc-mirror`,
create a registry or contact a cluster. They remain only to preserve the exact
evidence boundary of earlier certified phases. Phase 7 uses the laptop-local
Compose handoff in `../live/compose.template.yaml`.

For the supported laptop runtime, an operator must:

1. build the wheelhouse for the laptop architecture and verify its checksum;
2. build or import the four approved service images locally;
3. pin each image by digest in the Phase 7 release-set candidate;
4. start the `phase7-local` Compose profile with local secret files;
5. capture local network-denial, dependency-fault, restart and soak evidence;
6. record stakeholder acceptance separately.

No GCP, OpenShift or other remote-cluster resource is permitted by this flow.
