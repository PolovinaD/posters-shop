#!/bin/bash
# ============================================================
# Generate Kubernetes Secrets for PosterShop
# ============================================================
# Creates all required Kubernetes secrets for the platform.
#
# Required environment variables:
#   RDS_HOST              - RDS endpoint
#   RDS_DATABASE          - Database name (default: postershop)
#   USERS_SVC_PASSWORD    - Password for users_svc
#   CATALOG_SVC_PASSWORD  - Password for catalog_svc
#   ORDERS_SVC_PASSWORD   - Password for orders_svc
#   PRODUCTION_SVC_PASSWORD - Password for production_svc
#   LOGISTICS_SVC_PASSWORD  - Password for logistics_svc
#   INVENTORY_SVC_PASSWORD  - Password for inventory_svc
#   JWT_SECRET            - JWT signing key (will generate if not set)
#   STRIPE_WEBHOOK_SECRET - Stripe webhook secret
#
# Usage:
#   ./generate-secrets.sh [namespace]
#   ./generate-secrets.sh postershop --dry-run
# ============================================================

set -e

NAMESPACE=${1:-postershop}
DRY_RUN=""
if [[ "$2" == "--dry-run" ]] || [[ "$1" == "--dry-run" ]]; then
    DRY_RUN="--dry-run=client -o yaml"
    echo "🔍 Running in DRY RUN mode (will output YAML)"
fi

RDS_PORT=${RDS_PORT:-5432}
RDS_DATABASE=${RDS_DATABASE:-postershop}

echo "==================================================="
echo "🔐 Generating Kubernetes Secrets"
echo "   Namespace: $NAMESPACE"
echo "   RDS Host:  $RDS_HOST"
echo "==================================================="

# Check required variables
required_vars=(
    "RDS_HOST"
    "USERS_SVC_PASSWORD"
    "CATALOG_SVC_PASSWORD"
    "ORDERS_SVC_PASSWORD"
    "PRODUCTION_SVC_PASSWORD"
    "LOGISTICS_SVC_PASSWORD"
    "INVENTORY_SVC_PASSWORD"
)

missing_vars=0
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "❌ Missing: $var"
        missing_vars=1
    fi
done

if [ $missing_vars -eq 1 ]; then
    echo ""
    echo "Set missing variables or generate new passwords:"
    echo "  export USERS_SVC_PASSWORD=\$(openssl rand -base64 24)"
    exit 1
fi

# Generate JWT secret if not provided
if [ -z "$JWT_SECRET" ]; then
    JWT_SECRET=$(openssl rand -hex 32)
    echo "ℹ️  Generated JWT_SECRET (save this!): $JWT_SECRET"
fi

# Default Stripe webhook secret
STRIPE_WEBHOOK_SECRET=${STRIPE_WEBHOOK_SECRET:-whsec_placeholder_replace_with_real_secret}

# Build connection strings
DB_URL_BASE="postgresql://%s:%s@${RDS_HOST}:${RDS_PORT}/${RDS_DATABASE}?sslmode=require&options=-csearch_path%%3D%s"

echo ""
echo "📦 Creating/updating postershop-db secret..."
kubectl create secret generic postershop-db \
    --namespace="$NAMESPACE" \
    --from-literal=DATABASE_URL_USERS="$(printf "$DB_URL_BASE" "users_svc" "$USERS_SVC_PASSWORD" "users_schema")" \
    --from-literal=DATABASE_URL_CATALOG="$(printf "$DB_URL_BASE" "catalog_svc" "$CATALOG_SVC_PASSWORD" "catalog_schema")" \
    --from-literal=DATABASE_URL_ORDERS="$(printf "$DB_URL_BASE" "orders_svc" "$ORDERS_SVC_PASSWORD" "orders_schema")" \
    --from-literal=DATABASE_URL_PRODUCTION="$(printf "$DB_URL_BASE" "production_svc" "$PRODUCTION_SVC_PASSWORD" "production_schema")" \
    --from-literal=DATABASE_URL_LOGISTICS="$(printf "$DB_URL_BASE" "logistics_svc" "$LOGISTICS_SVC_PASSWORD" "logistics_schema")" \
    --from-literal=DATABASE_URL_INVENTORY="$(printf "$DB_URL_BASE" "inventory_svc" "$INVENTORY_SVC_PASSWORD" "inventory_schema")" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "📦 Creating/updating postershop-jwt secret..."
kubectl create secret generic postershop-jwt \
    --namespace="$NAMESPACE" \
    --from-literal=JWT_SECRET="$JWT_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "📦 Creating/updating postershop-stripe secret..."
kubectl create secret generic postershop-stripe \
    --namespace="$NAMESPACE" \
    --from-literal=WEBHOOK_SECRET="$STRIPE_WEBHOOK_SECRET" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "==================================================="
echo "✅ Secrets created successfully!"
echo ""
echo "Verify with:"
echo "  kubectl get secrets -n $NAMESPACE"
echo ""
echo "⚠️  Remember to save the generated passwords securely!"
echo "==================================================="

