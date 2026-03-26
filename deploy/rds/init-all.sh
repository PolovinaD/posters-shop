#!/bin/bash
# ============================================================
# PosterShop Platform - RDS Initialization Script
# ============================================================
# Runs all SQL scripts to initialize the RDS database.
#
# Required environment variables:
#   RDS_HOST              - RDS endpoint
#   RDS_PORT              - RDS port (default: 5432)
#   RDS_DATABASE          - Database name (default: postershop)
#   RDS_MASTER_USER       - Master username
#   RDS_MASTER_PASSWORD   - Master password
#   USERS_SVC_PASSWORD    - Password for users_svc
#   CATALOG_SVC_PASSWORD  - Password for catalog_svc
#   ORDERS_SVC_PASSWORD   - Password for orders_svc
#   PRODUCTION_SVC_PASSWORD - Password for production_svc
#   LOGISTICS_SVC_PASSWORD  - Password for logistics_svc
#   INVENTORY_SVC_PASSWORD  - Password for inventory_svc
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default values
RDS_PORT=${RDS_PORT:-5432}
RDS_DATABASE=${RDS_DATABASE:-postershop}

# Validate required variables
required_vars=(
    "RDS_HOST"
    "RDS_MASTER_USER"
    "RDS_MASTER_PASSWORD"
    "USERS_SVC_PASSWORD"
    "CATALOG_SVC_PASSWORD"
    "ORDERS_SVC_PASSWORD"
    "PRODUCTION_SVC_PASSWORD"
    "LOGISTICS_SVC_PASSWORD"
    "INVENTORY_SVC_PASSWORD"
)

echo "==================================================="
echo "🚀 PosterShop RDS Initialization"
echo "   Host:     $RDS_HOST"
echo "   Port:     $RDS_PORT"
echo "   Database: $RDS_DATABASE"
echo "   User:     $RDS_MASTER_USER"
echo "==================================================="

missing_vars=0
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Missing required variable: $var"
        missing_vars=1
    fi
done

if [ $missing_vars -eq 1 ]; then
    echo ""
    echo "Please set all required environment variables."
    echo "Example:"
    echo "  export RDS_HOST=your-rds-endpoint.region.rds.amazonaws.com"
    echo "  export RDS_MASTER_USER=postgres"
    echo "  export RDS_MASTER_PASSWORD=your-master-password"
    echo "  export USERS_SVC_PASSWORD=\$(openssl rand -base64 24)"
    echo "  # ... etc"
    exit 1
fi

# Connection string
export PGPASSWORD="$RDS_MASTER_PASSWORD"
PSQL_CMD="psql -h $RDS_HOST -p $RDS_PORT -U $RDS_MASTER_USER -d $RDS_DATABASE"

# Test connection
echo ""
echo "📡 Testing connection..."
if ! $PSQL_CMD -c "SELECT 1" > /dev/null 2>&1; then
    echo "❌ Failed to connect to database"
    echo "   Check host, port, username, and password"
    exit 1
fi
echo "✅ Connected successfully"

# Step 1: Create schemas
echo ""
echo "📁 Creating schemas..."
$PSQL_CMD -f "$SCRIPT_DIR/01-create-schemas.sql"
echo "✅ Schemas created"

# Step 2: Create users (with password variables)
echo ""
echo "👤 Creating service users..."
$PSQL_CMD \
    -v users_pass="$USERS_SVC_PASSWORD" \
    -v catalog_pass="$CATALOG_SVC_PASSWORD" \
    -v orders_pass="$ORDERS_SVC_PASSWORD" \
    -v production_pass="$PRODUCTION_SVC_PASSWORD" \
    -v logistics_pass="$LOGISTICS_SVC_PASSWORD" \
    -v inventory_pass="$INVENTORY_SVC_PASSWORD" \
    -f "$SCRIPT_DIR/02-create-users.sql"
echo "✅ Users created"

# Step 3: Grant permissions
echo ""
echo "🔐 Granting permissions..."
$PSQL_CMD -f "$SCRIPT_DIR/03-grant-permissions.sql"
echo "✅ Permissions granted"

# Summary
echo ""
echo "==================================================="
echo "✅ RDS initialization complete!"
echo ""
echo "📝 Connection strings for Kubernetes secrets:"
echo ""
echo "DATABASE_URL_USERS:"
echo "  postgresql://users_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dusers"
echo ""
echo "DATABASE_URL_CATALOG:"
echo "  postgresql://catalog_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dcatalog"
echo ""
echo "DATABASE_URL_ORDERS:"
echo "  postgresql://orders_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dorders"
echo ""
echo "DATABASE_URL_PRODUCTION:"
echo "  postgresql://production_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dproduction"
echo ""
echo "DATABASE_URL_LOGISTICS:"
echo "  postgresql://logistics_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dlogistics"
echo ""
echo "DATABASE_URL_INVENTORY:"
echo "  postgresql://inventory_svc:****@$RDS_HOST:$RDS_PORT/$RDS_DATABASE?sslmode=require&options=-csearch_path%3Dinventory"
echo ""
echo "⚠️  Save the service passwords to AWS Secrets Manager!"
echo "==================================================="

