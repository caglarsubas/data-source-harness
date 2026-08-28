# White-goods runtime transfer packet

This directory is an air-gap transfer scaffold, not deployed-runtime evidence.
It binds the harness wheel, worker/protocol contracts, cross-plane revision set,
the inert Phase 7 live-service handoff and OpenShift templates into a
deterministic signed archive.

Before deployment, an operator must:

1. build the wheelhouse for a Python version matching the approved base image
   (the default recipe targets CPython 3.11 on Linux x86-64), then verify its
   generated checksum manifest;
2. build and scan the runtime image;
3. replace every image placeholder in `mirroring/imageset-config.template.yaml`
   with an approved immutable digest;
4. mirror images and signatures into the disconnected registry using the
   supported `oc-mirror` v2 process;
5. apply the overlay through the OCP reference-lab process;
6. capture network-denial, dependency-fault and restart evidence;
7. record stakeholder acceptance separately.

The Phase-6.5 certificate passes when this packet is complete and fail-closed
about those missing gates. It does not turn the packet into an OpenShift
certification.

The OpenShift templates include health/readiness probes, a ClusterIP service,
configuration mounting, default-deny networking and a separate internal-only
allow policy. Namespace labels are an explicit deployment input; the templates
do not grant access to arbitrary namespaces or public destinations.
