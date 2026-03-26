-- ============================================================
-- PosterShop Platform - Schema Creation
-- ============================================================
-- Creates isolated schemas for each microservice.
-- Run as: RDS master user (postgres)
-- ============================================================

-- Users service schema (authentication, user profiles)
CREATE SCHEMA IF NOT EXISTS users;
COMMENT ON SCHEMA users IS 'User authentication and profile management';

-- Catalog service schema (products, sizes, frames)
CREATE SCHEMA IF NOT EXISTS catalog;
COMMENT ON SCHEMA catalog IS 'Product catalog and pricing';

-- Orders service schema (orders, order items, outbox)
CREATE SCHEMA IF NOT EXISTS orders;
COMMENT ON SCHEMA orders IS 'Order management and checkout';

-- Production service schema (production jobs, queue)
CREATE SCHEMA IF NOT EXISTS production;
COMMENT ON SCHEMA production IS 'Manufacturing job tracking';

-- Logistics service schema (shipments, tracking)
CREATE SCHEMA IF NOT EXISTS logistics;
COMMENT ON SCHEMA logistics IS 'Shipping and delivery management';

-- Inventory service schema (stock, reservations)
CREATE SCHEMA IF NOT EXISTS inventory;
COMMENT ON SCHEMA inventory IS 'Stock levels and reservations';

-- Verify schemas created
SELECT schema_name, 
       pg_catalog.obj_description(oid, 'pg_namespace') as description
FROM information_schema.schemata s
JOIN pg_namespace n ON s.schema_name = n.nspname
WHERE schema_name IN ('users', 'catalog', 'orders', 'production', 'logistics', 'inventory')
ORDER BY schema_name;

