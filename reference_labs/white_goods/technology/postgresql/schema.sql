CREATE TABLE products (
  product_id TEXT PRIMARY KEY,
  model_code TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  launch_date DATE NOT NULL,
  warranty_months INTEGER NOT NULL CHECK (warranty_months > 0)
);

CREATE TABLE customers (
  customer_id TEXT PRIMARY KEY,
  region TEXT NOT NULL,
  service_tier TEXT NOT NULL,
  analytics_consent BOOLEAN NOT NULL
);

CREATE TABLE installed_products (
  serial_number TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(product_id),
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  installed_at DATE NOT NULL
);

CREATE TABLE service_orders (
  service_order_id TEXT PRIMARY KEY,
  serial_number TEXT NOT NULL REFERENCES installed_products(serial_number),
  customer_id TEXT NOT NULL REFERENCES customers(customer_id),
  opened_at TIMESTAMPTZ NOT NULL,
  closed_at TIMESTAMPTZ,
  error_code TEXT,
  symptom TEXT NOT NULL,
  resolution TEXT,
  visit_number INTEGER NOT NULL CHECK (visit_number > 0)
);

CREATE TABLE quality_inspections (
  inspection_id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(product_id),
  lot_id TEXT NOT NULL,
  inspected_at TIMESTAMPTZ NOT NULL,
  check_name TEXT NOT NULL,
  result TEXT NOT NULL CHECK (result IN ('pass', 'fail')),
  measurement NUMERIC
);
