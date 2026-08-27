# White-goods runtime transfer packet

This directory is an air-gap transfer scaffold, not deployed-runtime evidence.
It binds the harness wheel, worker/protocol contracts, cross-plane revision set,
and OpenShift templates into a deterministic signed archive.

Before deployment, an operator must:

1. build and scan the runtime image;
2. replace every image placeholder with an approved immutable digest;
3. mirror images and signatures into the disconnected registry;
4. apply the overlay through the OCP reference-lab process;
5. capture network-denial, dependency-fault and restart evidence;
6. record stakeholder acceptance separately.

The Phase-6 certificate passes when this packet is complete and fail-closed
about those missing gates. It does not turn the packet into an OpenShift
certification.
