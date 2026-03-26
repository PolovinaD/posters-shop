-- Create schemas
CREATE SCHEMA IF NOT EXISTS users;
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE SCHEMA IF NOT EXISTS orders;
CREATE SCHEMA IF NOT EXISTS production;
CREATE SCHEMA IF NOT EXISTS logistics;
CREATE SCHEMA IF NOT EXISTS inventory;

-- Create service-specific users
CREATE USER users_svc WITH PASSWORD 'users_pass';
CREATE USER catalog_svc WITH PASSWORD 'catalog_pass';
CREATE USER orders_svc WITH PASSWORD 'orders_pass';
CREATE USER production_svc WITH PASSWORD 'production_pass';
CREATE USER logistics_svc WITH PASSWORD 'logistics_pass';
CREATE USER inventory_svc WITH PASSWORD 'inventory_pass';

-- Grant schema-specific permissions for users service
GRANT USAGE, CREATE ON SCHEMA users TO users_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO users_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT ALL ON TABLES TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT ALL ON SEQUENCES TO users_svc;

-- Grant schema-specific permissions for catalog service
GRANT USAGE, CREATE ON SCHEMA catalog TO catalog_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog TO catalog_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON TABLES TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON SEQUENCES TO catalog_svc;

-- Grant schema-specific permissions for orders service
GRANT USAGE, CREATE ON SCHEMA orders TO orders_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA orders TO orders_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA orders TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders GRANT ALL ON TABLES TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders GRANT ALL ON SEQUENCES TO orders_svc;

-- Grant schema-specific permissions for production service
GRANT USAGE, CREATE ON SCHEMA production TO production_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA production TO production_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA production TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production GRANT ALL ON TABLES TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production GRANT ALL ON SEQUENCES TO production_svc;

-- Grant schema-specific permissions for logistics service
GRANT USAGE, CREATE ON SCHEMA logistics TO logistics_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA logistics TO logistics_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA logistics TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics GRANT ALL ON TABLES TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics GRANT ALL ON SEQUENCES TO logistics_svc;

-- Grant schema-specific permissions for inventory service
GRANT USAGE, CREATE ON SCHEMA inventory TO inventory_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory TO inventory_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON TABLES TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON SEQUENCES TO inventory_svc;
