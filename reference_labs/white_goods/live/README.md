# Phase 7 local-laptop service handoff

`compose.template.yaml` is an inert operator handoff for the four representative
local source shapes. Every service is behind the explicit `phase7-local` profile,
has no host-published port, and joins an internal-only network. Images have no
defaults: an operator must preload and supply an approved digest reference for PostgreSQL,
MinIO, Redpanda and the contract-backed service API. Credentials enter through
ephemeral environment-backed Compose secrets and are not committed or written by the harness.

The template is packaged and statically checked by `make phase7-readiness` but
is not started by CI. `make phase7-local-sources` is the explicit laptop-only
lifecycle: it requires PostgreSQL, MinIO, Redpanda `v26.2.2` and Python images
to exist locally, builds the REST image with `--pull=false`, starts and seeds the
four services, verifies them and tears the topology down.
`pull_policy: never` prevents an implicit registry pull. The campaign may not
provision GCP, OpenShift or any remote cluster. A successful Compose start is
still only local-source evidence; it is not combined-platform publication,
startup, runtime, fault, soak or stakeholder evidence.

`make phase7-local-cross-plane` separately exercises mature neighboring
repositories. It reads exact local `origin/main` source without modifying those
checkouts, uses the preloaded ADLC builder image only as an offline TypeScript
execution tool, and invokes the model-plane's local virtual environment. The
result proves SDK receipt, ADLC validation and tenant-bound rerank contracts;
it is not a production-image or full-platform startup claim.

`make phase7-local-harness` builds a revision-labelled ARM64 acceptance image
from the locally available Python base, harness wheel and pinned binary wheels.
It joins the internal-only network and runs the actual connector gateway
against PostgreSQL, MinIO, Redpanda and the authenticated service API. The
acceptance image has no published port and Compose uses `pull_policy: never`.

The existing `docker-compose.yml` remains a development topology for synthetic
fixtures. It must not be cited as Phase 7 evidence.
