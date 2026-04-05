#!/bin/bash
# ============================================================
# PosterShop Platform - Kubernetes Deployment Script
# ============================================================
# This script deploys all microservices to a Kubernetes cluster.
#
# Prerequisites:
#   - kubectl configured with cluster access
#   - helm v3 installed
#   - Secrets already applied (see secrets-template.yaml)
#
# Usage:
#   ./deploy.sh [namespace] [--dry-run]
#
# Examples:
#   ./deploy.sh                    # Deploy to 'postershop' namespace
#   ./deploy.sh staging            # Deploy to 'staging' namespace
#   ./deploy.sh production --dry-run  # Dry run for production
# ============================================================

set -e

NAMESPACE=${1:-postershop}
DRY_RUN=""
if [ "$2" == "--dry-run" ]; then
    DRY_RUN="--dry-run"
    echo "🔍 Running in DRY RUN mode"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
CHARTS_DIR="$SCRIPT_DIR/charts"

# Load .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    echo "📄 Loading configuration from .env"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# AWS Configuration (auto-detect if not set)
AWS_REGION=${AWS_REGION:-eu-north-1}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "=================================================="
echo "🚀 Deploying PosterShop Platform"
echo "   Namespace:    $NAMESPACE"
echo "   Charts:       $CHARTS_DIR"
echo "   ECR Registry: $ECR_REGISTRY"
echo "=================================================="

# Create namespace if it doesn't exist
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "📁 Creating namespace: $NAMESPACE"
    kubectl create namespace "$NAMESPACE" $DRY_RUN
fi

# Check if secrets exist
echo ""
echo "🔐 Checking secrets..."
SECRETS=("postershop-db" "postershop-jwt" "postershop-stripe")
for secret in "${SECRETS[@]}"; do
    if kubectl get secret "$secret" -n "$NAMESPACE" &>/dev/null; then
        echo "   ✅ $secret exists"
    else
        echo "   ❌ $secret NOT FOUND - please create it first!"
        echo "      See: deploy/secrets-template.yaml"
        exit 1
    fi
done

# Define services in deployment order (dependencies first)
SERVICES=(
    "inventory"      # No dependencies
    "payments"       # No dependencies
    "users"          # No dependencies
    "catalog"        # Depends on inventory
    "logistics"      # Depends on orders (but orders depends on others, so deploy logistics first)
    "production"     # Depends on orders, logistics
    "orders"         # Depends on inventory, production, payments
    "infra"          # Infrastructure management service
    "frontend"       # Depends on all services (public-facing)
)

echo ""
echo "📦 Deploying services..."
for service in "${SERVICES[@]}"; do
    CHART_PATH="$CHARTS_DIR/$service"

    if [ -d "$CHART_PATH" ]; then
        echo ""
        echo "   🔄 Deploying: $service"

        helm upgrade --install "$service" "$CHART_PATH" \
            --namespace "$NAMESPACE" \
            --set image.repository="${ECR_REGISTRY}/${service}" \
            --wait \
            --timeout 5m \
            $DRY_RUN

        # Patch CORS_ORIGINS via kubectl after deploy — avoids Helm list --set replacing
        # the entire env array and stripping name: fields from all other env vars.
        # infra uses dict-format env in its chart (safe to --set); all others patched here.
        if [ -n "${CORS_ORIGINS:-}" ] && [ "$service" != "infra" ] && [ "$DRY_RUN" != "--dry-run" ]; then
            kubectl set env deployment/"$service" -n "$NAMESPACE" CORS_ORIGINS="${CORS_ORIGINS}" 2>/dev/null || true
        fi

        # After frontend deploys, resolve ALB hostname and patch payments FRONTEND_URL
        if [ "$service" = "frontend" ] && [ "$DRY_RUN" != "--dry-run" ]; then
            echo "   ⏳ Waiting for ALB hostname..."
            for i in $(seq 1 24); do
                ALB_HOST=$(kubectl get ingress frontend -n "$NAMESPACE" \
                    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)
                if [ -n "$ALB_HOST" ]; then break; fi
                sleep 5
            done
            if [ -n "$ALB_HOST" ]; then
                echo "   🌐 ALB: http://$ALB_HOST"
                kubectl set env deployment/payments -n "$NAMESPACE" \
                    FRONTEND_URL="http://$ALB_HOST" 2>/dev/null || true
                echo "   ✅ payments FRONTEND_URL patched"
            else
                echo "   ⚠️  ALB hostname not ready — patch payments FRONTEND_URL manually"
            fi
        fi

        echo "   ✅ $service deployed"
    else
        echo "   ⚠️  Chart not found: $CHART_PATH"
    fi
done

echo ""
echo "=================================================="
echo "✅ Deployment complete!"
echo ""
echo "📊 Check status:"
echo "   kubectl get pods -n $NAMESPACE"
echo "   kubectl get svc -n $NAMESPACE"
echo "   kubectl get ingress -n $NAMESPACE"
echo ""
echo "🌐 Get frontend URL (ALB):"
echo "   kubectl get ingress frontend -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'"
echo "=================================================="

