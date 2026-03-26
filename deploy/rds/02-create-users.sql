-- ============================================================
-- PosterShop Platform - Service User Creation
-- ============================================================
-- Creates database users for each microservice.
-- Run as: RDS master user (postgres)
--
-- IMPORTANT: Replace placeholder passwords before running!
-- Generate secure passwords with: openssl rand -base64 24
--
-- For automated setup, use psql variables:
--   psql -v users_pass="'secure_password'" -f 02-create-users.sql
-- ============================================================

-- Create users (will fail if already exists - that's OK)
DO $$
BEGIN
    -- Users service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'users_svc') THEN
        CREATE USER users_svc WITH PASSWORD :'users_pass';
        RAISE NOTICE 'Created user: users_svc';
    ELSE
        -- Update password if user exists
        EXECUTE format('ALTER USER users_svc WITH PASSWORD %L', :'users_pass');
        RAISE NOTICE 'Updated password for: users_svc';
    END IF;

    -- Catalog service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
        CREATE USER catalog_svc WITH PASSWORD :'catalog_pass';
        RAISE NOTICE 'Created user: catalog_svc';
    ELSE
        EXECUTE format('ALTER USER catalog_svc WITH PASSWORD %L', :'catalog_pass');
        RAISE NOTICE 'Updated password for: catalog_svc';
    END IF;

    -- Orders service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'orders_svc') THEN
        CREATE USER orders_svc WITH PASSWORD :'orders_pass';
        RAISE NOTICE 'Created user: orders_svc';
    ELSE
        EXECUTE format('ALTER USER orders_svc WITH PASSWORD %L', :'orders_pass');
        RAISE NOTICE 'Updated password for: orders_svc';
    END IF;

    -- Production service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'production_svc') THEN
        CREATE USER production_svc WITH PASSWORD :'production_pass';
        RAISE NOTICE 'Created user: production_svc';
    ELSE
        EXECUTE format('ALTER USER production_svc WITH PASSWORD %L', :'production_pass');
        RAISE NOTICE 'Updated password for: production_svc';
    END IF;

    -- Logistics service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'logistics_svc') THEN
        CREATE USER logistics_svc WITH PASSWORD :'logistics_pass';
        RAISE NOTICE 'Created user: logistics_svc';
    ELSE
        EXECUTE format('ALTER USER logistics_svc WITH PASSWORD %L', :'logistics_pass');
        RAISE NOTICE 'Updated password for: logistics_svc';
    END IF;

    -- Inventory service
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'inventory_svc') THEN
        CREATE USER inventory_svc WITH PASSWORD :'inventory_pass';
        RAISE NOTICE 'Created user: inventory_svc';
    ELSE
        EXECUTE format('ALTER USER inventory_svc WITH PASSWORD %L', :'inventory_pass');
        RAISE NOTICE 'Updated password for: inventory_svc';
    END IF;
END
$$;

-- Verify users created
SELECT usename, usecreatedb, usesuper 
FROM pg_user 
WHERE usename LIKE '%_svc'
ORDER BY usename;

