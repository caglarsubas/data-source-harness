\copy products FROM '/fixtures/master/products.csv' WITH (FORMAT csv, HEADER true);
\copy customers FROM '/fixtures/master/customers.csv' WITH (FORMAT csv, HEADER true);
\copy installed_products FROM '/fixtures/master/installed_products.csv' WITH (FORMAT csv, HEADER true);
\copy service_orders FROM '/fixtures/service/service_orders.csv' WITH (FORMAT csv, HEADER true);
\copy quality_inspections FROM '/fixtures/quality/quality_inspections.csv' WITH (FORMAT csv, HEADER true);

-- Mutable-reference-lab state is deliberately local and disposable. The
-- record version supplies an optimistic concurrency boundary; the idempotency
-- table makes replay protection survive a gateway process restart.
ALTER TABLE service_orders ADD COLUMN record_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE harness_action_idempotency (
  idempotency_key TEXT PRIMARY KEY,
  action_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  source_version INTEGER NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
