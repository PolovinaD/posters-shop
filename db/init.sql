-- PosterShop Local Dev Database Initialization
-- Mirrors deploy/full-deploy.sh prod path with hardcoded dev passwords

-- Create schemas
CREATE SCHEMA IF NOT EXISTS users_schema;
CREATE SCHEMA IF NOT EXISTS catalog_schema;
CREATE SCHEMA IF NOT EXISTS orders_schema;
CREATE SCHEMA IF NOT EXISTS production_schema;
CREATE SCHEMA IF NOT EXISTS logistics_schema;
CREATE SCHEMA IF NOT EXISTS inventory_schema;

-- Drop existing users if they exist (for idempotency)
DROP USER IF EXISTS users_svc;
DROP USER IF EXISTS catalog_svc;
DROP USER IF EXISTS orders_svc;
DROP USER IF EXISTS production_svc;
DROP USER IF EXISTS logistics_svc;
DROP USER IF EXISTS inventory_svc;

-- Create service users (hardcoded dev passwords -- local only)
CREATE USER users_svc WITH PASSWORD 'users_pass';
CREATE USER catalog_svc WITH PASSWORD 'catalog_pass';
CREATE USER orders_svc WITH PASSWORD 'orders_pass';
CREATE USER production_svc WITH PASSWORD 'production_pass';
CREATE USER logistics_svc WITH PASSWORD 'logistics_pass';
CREATE USER inventory_svc WITH PASSWORD 'inventory_pass';

-- Grant permissions - each service only accesses its own schema
GRANT USAGE ON SCHEMA users_schema TO users_svc;
GRANT ALL PRIVILEGES ON SCHEMA users_schema TO users_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users_schema TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users_schema GRANT ALL ON TABLES TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users_schema GRANT ALL ON SEQUENCES TO users_svc;

GRANT USAGE ON SCHEMA catalog_schema TO catalog_svc;
GRANT ALL PRIVILEGES ON SCHEMA catalog_schema TO catalog_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog_schema TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog_schema GRANT ALL ON TABLES TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog_schema GRANT ALL ON SEQUENCES TO catalog_svc;

GRANT USAGE ON SCHEMA orders_schema TO orders_svc;
GRANT ALL PRIVILEGES ON SCHEMA orders_schema TO orders_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA orders_schema TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders_schema GRANT ALL ON TABLES TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders_schema GRANT ALL ON SEQUENCES TO orders_svc;

GRANT USAGE ON SCHEMA production_schema TO production_svc;
GRANT ALL PRIVILEGES ON SCHEMA production_schema TO production_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA production_schema TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production_schema GRANT ALL ON TABLES TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production_schema GRANT ALL ON SEQUENCES TO production_svc;

GRANT USAGE ON SCHEMA logistics_schema TO logistics_svc;
GRANT ALL PRIVILEGES ON SCHEMA logistics_schema TO logistics_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA logistics_schema TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics_schema GRANT ALL ON TABLES TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics_schema GRANT ALL ON SEQUENCES TO logistics_svc;

GRANT USAGE ON SCHEMA inventory_schema TO inventory_svc;
GRANT ALL PRIVILEGES ON SCHEMA inventory_schema TO inventory_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory_schema TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory_schema GRANT ALL ON TABLES TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory_schema GRANT ALL ON SEQUENCES TO inventory_svc;

-- Grant CREATE on database so Alembic env.py can run CREATE SCHEMA IF NOT EXISTS.
-- Resolved at runtime via current_database() so this works for any POSTGRES_DB value
-- (default `postershop` or .env override like `posters_shop`).
DO $$
BEGIN
  EXECUTE format('GRANT CREATE ON DATABASE %I TO users_svc, catalog_svc, orders_svc, production_svc, logistics_svc, inventory_svc', current_database());
END $$;

-- Done
SELECT 'Database initialization complete' as status;
