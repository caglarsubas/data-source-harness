\copy products FROM '/fixtures/master/products.csv' WITH (FORMAT csv, HEADER true);
\copy customers FROM '/fixtures/master/customers.csv' WITH (FORMAT csv, HEADER true);
\copy installed_products FROM '/fixtures/master/installed_products.csv' WITH (FORMAT csv, HEADER true);
\copy service_orders FROM '/fixtures/service/service_orders.csv' WITH (FORMAT csv, HEADER true);
\copy quality_inspections FROM '/fixtures/quality/quality_inspections.csv' WITH (FORMAT csv, HEADER true);
