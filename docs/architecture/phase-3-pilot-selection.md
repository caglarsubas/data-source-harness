# Phase 3 pilot selection

Cold-chain logistics was selected as the second pilot because it introduces a different buyer and operating model while exercising a capability mix that the white-goods lab does not fully cover: shipment hierarchies, continuous condition telemetry, route milestones, carrier APIs and time-critical incident response.

The selection was based on capability diversity and buyer value, not claims about a specific customer's stack. The representative stack is PostgreSQL for shipment/master data, MQTT-style telemetry, REST/OpenAPI carrier integration and S3/MinIO documents. Every fixture is synthetic and can run without internet access.

The proof boundary is intentionally narrow: a second pack must be generated and certified using the unchanged Phase-2 JSON schemas. Live carrier connectivity, production-scale telemetry, field validation and stakeholder approval remain future evidence states.
