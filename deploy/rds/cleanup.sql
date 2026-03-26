-- ============================================================
-- PosterShop Platform - Cleanup Script
-- ============================================================
-- Drops all service users and schemas.
-- WARNING: This will DELETE ALL DATA!
-- Run as: RDS master user (postgres)
-- ============================================================

-- Confirm before running (comment out to execute)
DO $$
BEGIN
    RAISE EXCEPTION 'SAFETY CHECK: Comment out this block to allow cleanup';
END
$$;

-- Revoke all privileges first
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA users FROM users_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users FROM users_svc;
REVOKE ALL PRIVILEGES ON SCHEMA users FROM users_svc;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog FROM catalog_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog FROM catalog_svc;
REVOKE ALL PRIVILEGES ON SCHEMA catalog FROM catalog_svc;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA orders FROM orders_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA orders FROM orders_svc;
REVOKE ALL PRIVILEGES ON SCHEMA orders FROM orders_svc;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA production FROM production_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA production FROM production_svc;
REVOKE ALL PRIVILEGES ON SCHEMA production FROM production_svc;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA logistics FROM logistics_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA logistics FROM logistics_svc;
REVOKE ALL PRIVILEGES ON SCHEMA logistics FROM logistics_svc;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory FROM inventory_svc;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory FROM inventory_svc;
REVOKE ALL PRIVILEGES ON SCHEMA inventory FROM inventory_svc;

-- Drop users
DROP USER IF EXISTS users_svc;
DROP USER IF EXISTS catalog_svc;
DROP USER IF EXISTS orders_svc;
DROP USER IF EXISTS production_svc;
DROP USER IF EXISTS logistics_svc;
DROP USER IF EXISTS inventory_svc;

-- Drop schemas (CASCADE will drop all tables!)
DROP SCHEMA IF EXISTS users CASCADE;
DROP SCHEMA IF EXISTS catalog CASCADE;
DROP SCHEMA IF EXISTS orders CASCADE;
DROP SCHEMA IF EXISTS production CASCADE;
DROP SCHEMA IF EXISTS logistics CASCADE;
DROP SCHEMA IF EXISTS inventory CASCADE;

-- Verify cleanup
SELECT 'Remaining schemas:' as info;
SELECT schema_name FROM information_schema.schemata 
WHERE schema_name IN ('users', 'catalog', 'orders', 'production', 'logistics', 'inventory');

SELECT 'Remaining users:' as info;
SELECT usename FROM pg_user WHERE usename LIKE '%_svc';

