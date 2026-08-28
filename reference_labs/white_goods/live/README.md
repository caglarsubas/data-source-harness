# Phase 7 local-laptop service handoff

`compose.template.yaml` is an inert operator handoff for the four representative
local source shapes. Every service is behind the explicit `phase7-local` profile,
has no host-published port, and joins an internal-only network. Images have no
defaults: an operator must preload and supply an approved digest reference for PostgreSQL,
MinIO, Redpanda and the contract-backed service API. Credentials enter through
local secret files and are not committed.

The template is packaged and statically checked by `make phase7-readiness` but
is not started by CI or certification. Before an operator runs it, the approved
image digests must be copied into a new Phase 7 release-set candidate.
`pull_policy: never` prevents an implicit registry pull. The campaign may not
provision GCP, OpenShift or any remote cluster. A successful Compose start is
still only local-source evidence; it is not publication, zero-egress, fault,
soak or stakeholder evidence.

The existing `docker-compose.yml` remains a development topology for synthetic
fixtures. It must not be cited as Phase 7 evidence.
