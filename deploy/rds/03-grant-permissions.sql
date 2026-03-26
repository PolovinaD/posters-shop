-- ============================================================
-- PosterShop Platform - Permission Grants
-- ============================================================
-- Grants schema-level permissions to each service user.
-- Each user can only access their own schema.
-- Run as: RDS master user (postgres)
-- ============================================================

-- ============== Users Service ==============
-- Grant schema access
GRANT USAGE, CREATE ON SCHEMA users TO users_svc;

-- Grant table permissions (existing and future)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA users TO users_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA users TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT ALL ON TABLES TO users_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA users GRANT ALL ON SEQUENCES TO users_svc;

-- ============== Catalog Service ==============
GRANT USAGE, CREATE ON SCHEMA catalog TO catalog_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA catalog TO catalog_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA catalog TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON TABLES TO catalog_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT ALL ON SEQUENCES TO catalog_svc;

-- ============== Orders Service ==============
GRANT USAGE, CREATE ON SCHEMA orders TO orders_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA orders TO orders_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA orders TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders GRANT ALL ON TABLES TO orders_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA orders GRANT ALL ON SEQUENCES TO orders_svc;

-- ============== Production Service ==============
GRANT USAGE, CREATE ON SCHEMA production TO production_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA production TO production_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA production TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production GRANT ALL ON TABLES TO production_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA production GRANT ALL ON SEQUENCES TO production_svc;

-- ============== Logistics Service ==============
GRANT USAGE, CREATE ON SCHEMA logistics TO logistics_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA logistics TO logistics_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA logistics TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics GRANT ALL ON TABLES TO logistics_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA logistics GRANT ALL ON SEQUENCES TO logistics_svc;

-- ============== Inventory Service ==============
GRANT USAGE, CREATE ON SCHEMA inventory TO inventory_svc;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA inventory TO inventory_svc;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA inventory TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON TABLES TO inventory_svc;
ALTER DEFAULT PRIVILEGES IN SCHEMA inventory GRANT ALL ON SEQUENCES TO inventory_svc;

-- ============== Verify Permissions ==============
SELECT 
    n.nspname AS schema,
    r.rolname AS user,
    string_agg(DISTINCT privilege_type, ', ') AS privileges
FROM information_schema.role_usage_grants rug
JOIN pg_namespace n ON rug.object_schema = n.nspname
JOIN pg_roles r ON rug.grantee = r.rolname
WHERE r.rolname LIKE '%_svc'
GROUP BY n.nspname, r.rolname
ORDER BY n.nspname;

