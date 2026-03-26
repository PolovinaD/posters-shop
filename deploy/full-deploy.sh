#!/bin/bash
# ============================================================
# PosterShop Platform - Full Deployment Script
# ============================================================
# This script creates the complete infrastructure and deploys
# all services from scratch.
#
# What it does:
#   1. Creates EKS cluster (optional, if not exists)
#   2. Installs AWS Load Balancer Controller
#   3. Creates RDS PostgreSQL instance
#   4. Initializes database schemas and users
#   5. Creates Kubernetes secrets
#   6. Deploys all microservices
#   7. Installs monitoring stack
#   8. Displays access information
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - eksctl installed
#   - kubectl installed
#   - helm v3 installed
#   - psql client installed
#
# Usage:
#   ./full-deploy.sh [options]
#
# Options:
#   --skip-cluster    Skip EKS cluster creation
#   --skip-rds        Skip RDS creation
#   --skip-monitoring Skip monitoring stack
#   --dry-run         Show what would be done
#
# Environment variables:
#   AWS_REGION        AWS region (default: eu-north-1)
#   CLUSTER_NAME      EKS cluster name (default: postershop)
#   DB_PASSWORD       RDS master password (will prompt if not set)
# ============================================================

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    log_info "Loading configuration from .env"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration (can be overridden by .env or environment)
AWS_REGION=${AWS_REGION:-eu-north-1}
AWS_ACCOUNT_ID=${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}
CLUSTER_NAME=${CLUSTER_NAME:-postershop}
NAMESPACE=${NAMESPACE:-postershop}
MONITORING_NAMESPACE=monitoring
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# Node configuration
# t3.small: ~11 pods/node, t3.medium: ~17 pods/node, t3.large: ~35 pods/node
NODE_INSTANCE_TYPE=${NODE_INSTANCE_TYPE:-t3.large}
NODE_COUNT=${NODE_COUNT:-2}
NODE_MIN=${NODE_MIN:-1}
NODE_MAX=${NODE_MAX:-5}

# Docker build architecture (amd64 for EKS, arm64 for local Mac testing)
DOCKER_PLATFORM=${DOCKER_PLATFORM:-linux/amd64}

# Parse arguments
SKIP_CLUSTER=false
SKIP_RDS=false
SKIP_MONITORING=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-cluster) SKIP_CLUSTER=true; shift ;;
        --skip-rds) SKIP_RDS=true; shift ;;
        --skip-monitoring) SKIP_MONITORING=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# ============================================================
# Generate or Load Service Passwords
# ============================================================
# All passwords are stored exclusively in AWS Secrets Manager.
# No local files are used - AWS SM is the single source of truth.

generate_password() {
    openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24
}

load_or_generate_passwords() {
    # Try to load from AWS Secrets Manager
    if aws secretsmanager get-secret-value --secret-id postershop/passwords --region "$AWS_REGION" &> /dev/null; then
        log_info "Loading passwords from AWS Secrets Manager..."
        SECRET_JSON=$(aws secretsmanager get-secret-value --secret-id postershop/passwords --region "$AWS_REGION" --query SecretString --output text)
        export USERS_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.USERS_SVC_PASSWORD')
        export CATALOG_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.CATALOG_SVC_PASSWORD')
        export ORDERS_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.ORDERS_SVC_PASSWORD')
        export PRODUCTION_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.PRODUCTION_SVC_PASSWORD')
        export LOGISTICS_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.LOGISTICS_SVC_PASSWORD')
        export INVENTORY_SVC_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.INVENTORY_SVC_PASSWORD')
        export JWT_SECRET=$(echo "$SECRET_JSON" | jq -r '.JWT_SECRET')
        export STRIPE_WEBHOOK_SECRET=$(echo "$SECRET_JSON" | jq -r '.STRIPE_WEBHOOK_SECRET')
        export DB_PASSWORD=$(echo "$SECRET_JSON" | jq -r '.DB_PASSWORD // empty')
        log_success "Loaded passwords from AWS Secrets Manager"
        return 0
    fi
    
    # Generate new passwords (first run)
    log_info "Generating new passwords..."
    export USERS_SVC_PASSWORD=$(generate_password)
    export CATALOG_SVC_PASSWORD=$(generate_password)
    export ORDERS_SVC_PASSWORD=$(generate_password)
    export PRODUCTION_SVC_PASSWORD=$(generate_password)
    export LOGISTICS_SVC_PASSWORD=$(generate_password)
    export INVENTORY_SVC_PASSWORD=$(generate_password)
    export DB_PASSWORD=$(generate_password)
    export JWT_SECRET=$(openssl rand -hex 32)
    export STRIPE_WEBHOOK_SECRET="whsec_$(openssl rand -hex 16)"
    log_success "Passwords generated (will be stored in AWS Secrets Manager)"
}

load_or_generate_passwords

# Banner
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           PosterShop Platform - Full Deployment              ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Region:     $AWS_REGION                                     ║"
echo "║  Cluster:    $CLUSTER_NAME                                   ║"
echo "║  Namespace:  $NAMESPACE                                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
    echo ""
fi

# ============================================================
# Step 1: Prerequisites Check
# ============================================================
log_info "Step 1: Checking prerequisites..."

check_command() {
    if ! command -v $1 &> /dev/null; then
        log_error "$1 is required but not installed"
        exit 1
    fi
    echo "  ✓ $1"
}

check_command aws
check_command eksctl
check_command kubectl
check_command helm
check_command psql
check_command jq

# Verify AWS credentials
if ! aws sts get-caller-identity &> /dev/null; then
    log_error "AWS credentials not configured or expired"
    exit 1
fi
AWS_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
echo "  ✓ AWS Account: $AWS_ACCOUNT"

log_success "Prerequisites OK"
echo ""

# ============================================================
# Step 2: Create EKS Cluster
# ============================================================
if [ "$SKIP_CLUSTER" = false ]; then
    log_info "Step 2: Creating EKS cluster..."
    
    if eksctl get cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
        log_warn "Cluster '$CLUSTER_NAME' already exists, skipping creation"
    else
        if [ "$DRY_RUN" = true ]; then
            log_info "Would create cluster: $CLUSTER_NAME in $AWS_REGION"
        else
            # Generate eksctl config with correct cluster name
            EKSCTL_CONFIG=$(mktemp)
            cat > "$EKSCTL_CONFIG" << EKSCTL_EOF
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig

metadata:
  name: $CLUSTER_NAME
  region: $AWS_REGION
  version: "1.29"
  tags:
    project: postershop
    environment: dev

iam:
  withOIDC: true
  serviceAccounts:
    - metadata:
        name: aws-load-balancer-controller
        namespace: kube-system
      wellKnownPolicies:
        awsLoadBalancerController: true
    - metadata:
        name: external-dns
        namespace: kube-system
      wellKnownPolicies:
        externalDNS: true

vpc:
  cidr: 10.0.0.0/16
  nat:
    gateway: Single
  clusterEndpoints:
    publicAccess: true
    privateAccess: true

managedNodeGroups:
  - name: workers
    instanceType: $NODE_INSTANCE_TYPE
    desiredCapacity: $NODE_COUNT
    minSize: $NODE_MIN
    maxSize: $NODE_MAX
    volumeSize: 30
    volumeType: gp3
    privateNetworking: true
    labels:
      role: worker
    tags:
      project: postershop
    iam:
      withAddonPolicies:
        imageBuilder: true
        autoScaler: true
        ebs: true
        cloudWatch: true

addons:
  - name: vpc-cni
    version: latest
  - name: coredns
    version: latest
  - name: kube-proxy
    version: latest
  - name: aws-ebs-csi-driver
    version: latest
    wellKnownPolicies:
      ebsCSIController: true

cloudWatch:
  clusterLogging:
    enableTypes:
      - api
      - audit
      - authenticator
EKSCTL_EOF
            
            eksctl create cluster -f "$EKSCTL_CONFIG"
            rm -f "$EKSCTL_CONFIG"
            log_success "EKS cluster created"
        fi
    fi
else
    log_info "Step 2: Skipping EKS cluster creation (--skip-cluster)"
fi

# Configure kubectl
log_info "Configuring kubectl..."
if [ "$DRY_RUN" = false ]; then
    aws eks update-kubeconfig --region "$AWS_REGION" --name "$CLUSTER_NAME"
fi
echo ""

# ============================================================
# Step 3: Store Secrets in AWS Secrets Manager
# ============================================================
log_info "Step 3: Storing secrets in AWS Secrets Manager..."

store_secrets_in_aws() {
    local secret_name=$1
    local secret_value=$2
    
    if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$AWS_REGION" &> /dev/null; then
        log_info "Updating existing secret: $secret_name"
        aws secretsmanager put-secret-value \
            --secret-id "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" > /dev/null
    else
        log_info "Creating new secret: $secret_name"
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" \
            --tags Key=Project,Value=postershop Key=ManagedBy,Value=full-deploy > /dev/null
    fi
}

if [ "$DRY_RUN" = false ]; then
    # Store raw passwords (for DB init and reference)
    PASSWORDS_JSON=$(cat << EOF
{
    "USERS_SVC_PASSWORD": "$USERS_SVC_PASSWORD",
    "CATALOG_SVC_PASSWORD": "$CATALOG_SVC_PASSWORD",
    "ORDERS_SVC_PASSWORD": "$ORDERS_SVC_PASSWORD",
    "PRODUCTION_SVC_PASSWORD": "$PRODUCTION_SVC_PASSWORD",
    "LOGISTICS_SVC_PASSWORD": "$LOGISTICS_SVC_PASSWORD",
    "INVENTORY_SVC_PASSWORD": "$INVENTORY_SVC_PASSWORD",
    "DB_PASSWORD": "$DB_PASSWORD",
    "JWT_SECRET": "$JWT_SECRET",
    "STRIPE_WEBHOOK_SECRET": "$STRIPE_WEBHOOK_SECRET"
}
EOF
)
    store_secrets_in_aws "postershop/passwords" "$PASSWORDS_JSON"
    
    # Store JWT secret
    JWT_JSON=$(cat << EOF
{
    "JWT_SECRET": "$JWT_SECRET"
}
EOF
)
    store_secrets_in_aws "postershop/jwt" "$JWT_JSON"
    
    # Store Stripe secret
    STRIPE_JSON=$(cat << EOF
{
    "WEBHOOK_SECRET": "$STRIPE_WEBHOOK_SECRET"
}
EOF
)
    store_secrets_in_aws "postershop/stripe" "$STRIPE_JSON"
    
    log_success "Secrets stored in AWS Secrets Manager"
else
    log_info "Would store secrets in AWS Secrets Manager"
fi
echo ""

# ============================================================
# Step 4: Install AWS Load Balancer Controller
# ============================================================
log_info "Step 4: Installing AWS Load Balancer Controller..."

if [ "$DRY_RUN" = false ]; then
    # Add Helm repo
    helm repo add eks https://aws.github.io/eks-charts 2>/dev/null || true
    helm repo update
    
    # Install controller
    if ! helm status aws-load-balancer-controller -n kube-system &> /dev/null; then
        helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
            -n kube-system \
            --set clusterName="$CLUSTER_NAME" \
            --set serviceAccount.create=false \
            --set serviceAccount.name=aws-load-balancer-controller
        log_success "AWS Load Balancer Controller installed"
    else
        log_warn "AWS Load Balancer Controller already installed"
    fi
fi
echo ""

# ============================================================
# Step 5: Create RDS Instance
# ============================================================
if [ "$SKIP_RDS" = false ]; then
    log_info "Step 5: Creating RDS instance..."
    
    # Get VPC and subnets from EKS cluster
    VPC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" \
        --query 'cluster.resourcesVpcConfig.vpcId' --output text)
    
    SUBNET_IDS=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" \
        --query 'cluster.resourcesVpcConfig.subnetIds[:2]' --output text | tr '\t' ',' | tr -d '[:space:]')
    
    EKS_SG=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" \
        --query 'cluster.resourcesVpcConfig.clusterSecurityGroupId' --output text)
    
    echo "  VPC:     $VPC_ID"
    echo "  Subnets: $SUBNET_IDS"
    echo "  EKS SG:  $EKS_SG"
    
    # Verify DB_PASSWORD is set (loaded from AWS Secrets Manager at startup)
    if [ -z "$DB_PASSWORD" ]; then
        log_error "DB_PASSWORD not set. This should have been loaded from AWS Secrets Manager."
        exit 1
    fi
    
    STACK_NAME="postershop-rds"
    
    if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" &> /dev/null; then
        log_warn "RDS stack '$STACK_NAME' already exists"
    else
        if [ "$DRY_RUN" = true ]; then
            log_info "Would create RDS with CloudFormation"
        else
            # SubnetIds needs escaped commas for List parameter type
            SUBNET_LIST=$(echo "$SUBNET_IDS" | sed 's/,/\\,/g')
            aws cloudformation create-stack \
                --stack-name "$STACK_NAME" \
                --region "$AWS_REGION" \
                --template-body "file://$SCRIPT_DIR/infrastructure/rds.yaml" \
                --parameters \
                    "ParameterKey=VpcId,ParameterValue=$VPC_ID" \
                    "ParameterKey=SubnetIds,ParameterValue=$SUBNET_LIST" \
                    "ParameterKey=EKSSecurityGroupId,ParameterValue=$EKS_SG" \
                    "ParameterKey=MasterPassword,ParameterValue=$DB_PASSWORD"
            
            log_info "Waiting for RDS to be created (this takes ~10 minutes)..."
            aws cloudformation wait stack-create-complete --stack-name "$STACK_NAME" --region "$AWS_REGION"
            log_success "RDS instance created"
        fi
    fi
    
    # Get RDS endpoint
    RDS_ENDPOINT=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`DBEndpoint`].OutputValue' --output text)
    echo "  RDS Endpoint: $RDS_ENDPOINT"
else
    log_info "Step 5: Skipping RDS creation (--skip-rds)"
    # Try to get RDS endpoint from existing CloudFormation stack
    STACK_NAME="postershop-rds"
    if aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" &> /dev/null; then
        RDS_ENDPOINT=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$AWS_REGION" \
            --query 'Stacks[0].Outputs[?OutputKey==`DBEndpoint`].OutputValue' --output text)
        echo "  Found existing RDS: $RDS_ENDPOINT"
    elif [ -n "$RDS_ENDPOINT" ]; then
        echo "  Using provided RDS_ENDPOINT: $RDS_ENDPOINT"
    else
        log_error "No RDS endpoint found. Either create RDS or set RDS_ENDPOINT env var."
        exit 1
    fi
    
    # Verify DB_PASSWORD is set (loaded from AWS Secrets Manager at startup)
    if [ -z "$DB_PASSWORD" ]; then
        log_error "DB_PASSWORD not found in AWS Secrets Manager. Cannot initialize database."
        exit 1
    fi
fi
echo ""

# ============================================================
# Step 6: Initialize Database (via in-cluster Job)
# ============================================================
log_info "Step 6: Initializing database..."

if [ "$DRY_RUN" = false ] && [ -n "$RDS_ENDPOINT" ]; then
    # Passwords are already generated/loaded at script start
    
    # Create namespace first (needed for the init job)
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    
    # Create SQL init script
    INIT_SQL_FILE=$(mktemp)
    cat > "$INIT_SQL_FILE" << EOSQL
-- PosterShop Database Initialization
-- Creates schemas and service users with isolated permissions

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

-- Create service users
CREATE USER users_svc WITH PASSWORD '${USERS_SVC_PASSWORD}';
CREATE USER catalog_svc WITH PASSWORD '${CATALOG_SVC_PASSWORD}';
CREATE USER orders_svc WITH PASSWORD '${ORDERS_SVC_PASSWORD}';
CREATE USER production_svc WITH PASSWORD '${PRODUCTION_SVC_PASSWORD}';
CREATE USER logistics_svc WITH PASSWORD '${LOGISTICS_SVC_PASSWORD}';
CREATE USER inventory_svc WITH PASSWORD '${INVENTORY_SVC_PASSWORD}';

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

-- Done
SELECT 'Database initialization complete' as status;
EOSQL

    # Create ConfigMap with SQL script
    kubectl create configmap db-init-sql \
        --namespace="$NAMESPACE" \
        --from-file=init.sql="$INIT_SQL_FILE" \
        --dry-run=client -o yaml | kubectl apply -f -
    rm -f "$INIT_SQL_FILE"
    
    # Delete old init job if exists
    kubectl delete job db-init --namespace="$NAMESPACE" 2>/dev/null || true
    
    # Create and run init job
    log_info "Running database init job in cluster..."
    cat << EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: db-init
  namespace: $NAMESPACE
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: init
        image: postgres:16-alpine
        command: ["psql"]
        args:
        - "-h"
        - "$RDS_ENDPOINT"
        - "-U"
        - "postgres"
        - "-d"
        - "postershop"
        - "-f"
        - "/scripts/init.sql"
        env:
        - name: PGPASSWORD
          value: "$DB_PASSWORD"
        volumeMounts:
        - name: scripts
          mountPath: /scripts
      volumes:
      - name: scripts
        configMap:
          name: db-init-sql
EOF

    # Wait for job to complete
    log_info "Waiting for database init job to complete..."
    if kubectl wait --for=condition=complete job/db-init -n "$NAMESPACE" --timeout=120s; then
        log_success "Database initialized"
        kubectl logs job/db-init -n "$NAMESPACE" | tail -5
    else
        log_error "Database init job failed"
        kubectl logs job/db-init -n "$NAMESPACE"
        exit 1
    fi
fi
echo ""

# ============================================================
# Step 7: Install External Secrets Operator & Configure Secrets
# ============================================================
log_info "Step 7: Setting up External Secrets Operator..."

if [ "$DRY_RUN" = false ]; then
    # Create namespace
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    
    # Store database URLs in AWS Secrets Manager (now that we have RDS_ENDPOINT)
    export RDS_HOST="$RDS_ENDPOINT"
    DATABASE_JSON=$(cat << EOF
{
    "USERS_DATABASE_URL": "postgresql://users_svc:${USERS_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dusers_schema",
    "CATALOG_DATABASE_URL": "postgresql://catalog_svc:${CATALOG_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dcatalog_schema",
    "ORDERS_DATABASE_URL": "postgresql://orders_svc:${ORDERS_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dorders_schema",
    "PRODUCTION_DATABASE_URL": "postgresql://production_svc:${PRODUCTION_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dproduction_schema",
    "LOGISTICS_DATABASE_URL": "postgresql://logistics_svc:${LOGISTICS_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dlogistics_schema",
    "INVENTORY_DATABASE_URL": "postgresql://inventory_svc:${INVENTORY_SVC_PASSWORD}@${RDS_HOST}:5432/postershop?options=-c%20search_path%3Dinventory_schema"
}
EOF
)
    store_secrets_in_aws "postershop/database" "$DATABASE_JSON"
    log_success "Database URLs stored in AWS Secrets Manager"
    
    # Add External Secrets Helm repo
    helm repo add external-secrets https://charts.external-secrets.io 2>/dev/null || true
    helm repo update
    
    # Create IAM policy for ESO if it doesn't exist
    ESO_POLICY_NAME="postershop-external-secrets"
    if ! aws iam get-policy --policy-arn "arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${ESO_POLICY_NAME}" &> /dev/null; then
        log_info "Creating IAM policy for External Secrets..."
        aws iam create-policy \
            --policy-name "$ESO_POLICY_NAME" \
            --policy-document "file://$SCRIPT_DIR/secrets/iam-policy.json" > /dev/null
    fi
    
    # Create IRSA for External Secrets Operator
    log_info "Creating IRSA for External Secrets Operator..."
    eksctl create iamserviceaccount \
        --cluster="$CLUSTER_NAME" \
        --region="$AWS_REGION" \
        --namespace="$NAMESPACE" \
        --name=external-secrets-sa \
        --attach-policy-arn="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${ESO_POLICY_NAME}" \
        --approve \
        --override-existing-serviceaccounts 2>/dev/null || true
    
    # Install External Secrets Operator
    if ! helm status external-secrets -n external-secrets &> /dev/null; then
        log_info "Installing External Secrets Operator..."
        kubectl create namespace external-secrets --dry-run=client -o yaml | kubectl apply -f -
        helm install external-secrets external-secrets/external-secrets \
            -n external-secrets \
            --set installCRDs=true \
            --wait --timeout 5m
        log_success "External Secrets Operator installed"
    else
        log_warn "External Secrets Operator already installed"
    fi
    
    # Wait for CRDs to be established
    log_info "Waiting for External Secrets CRDs to be ready..."
    for crd in secretstores.external-secrets.io externalsecrets.external-secrets.io; do
        kubectl wait --for=condition=Established crd/$crd --timeout=60s 2>/dev/null || true
    done
    sleep 5  # Extra buffer for API server to register CRDs
    
    # Apply SecretStore (with region substitution)
    log_info "Creating SecretStore..."
    sed "s/\${AWS_REGION}/$AWS_REGION/g" "$SCRIPT_DIR/secrets/secret-store.yaml" | kubectl apply -f -
    
    # Apply ExternalSecrets
    log_info "Creating ExternalSecrets..."
    kubectl apply -f "$SCRIPT_DIR/secrets/external-secrets.yaml"
    
    # Wait for secrets to sync
    log_info "Waiting for secrets to sync from AWS Secrets Manager..."
    sleep 10
    for secret in postershop-db postershop-jwt postershop-stripe; do
        for i in {1..30}; do
            if kubectl get secret "$secret" -n "$NAMESPACE" &> /dev/null; then
                echo "  ✓ $secret synced"
                break
            fi
            sleep 2
        done
    done
    
    log_success "External Secrets configured"
fi
echo ""

# ============================================================
# Step 8: Build and Push Docker Images
# ============================================================
log_info "Step 8: Building and pushing Docker images..."

if [ "$DRY_RUN" = false ]; then
    # Login to ECR
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"
    
    SERVICES="users catalog orders production logistics inventory payments frontend infra"
    
    for svc in $SERVICES; do
        log_info "Building $svc..."
        
        if [ "$svc" = "frontend" ]; then
            BUILD_PATH="$PROJECT_ROOT/frontend"
        else
            BUILD_PATH="$PROJECT_ROOT/services/$svc"
        fi
        
        # Create ECR repo if not exists
        aws ecr describe-repositories --repository-names "$svc" --region "$AWS_REGION" &> /dev/null || \
            aws ecr create-repository --repository-name "$svc" --region "$AWS_REGION"
        
        # Build and push (use DOCKER_PLATFORM for cross-platform builds)
        docker build --platform "$DOCKER_PLATFORM" -t "$ECR_REGISTRY/$svc:latest" "$BUILD_PATH"
        docker push "$ECR_REGISTRY/$svc:latest"
        
        echo "  ✓ $svc pushed"
    done
    
    log_success "All images pushed to ECR"
fi
echo ""

# ============================================================
# Step 9: Deploy Services
# ============================================================
log_info "Step 9: Deploying services..."

if [ "$DRY_RUN" = false ]; then
    "$SCRIPT_DIR/deploy.sh" "$NAMESPACE"
    log_success "Services deployed"
fi
echo ""

# ============================================================
# Step 10: Install Monitoring
# ============================================================
if [ "$SKIP_MONITORING" = false ]; then
    log_info "Step 10: Installing monitoring stack..."
    
    if [ "$DRY_RUN" = false ]; then
        # Add Prometheus repo
        helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
        helm repo update
        
        # Create monitoring namespace
        kubectl create namespace "$MONITORING_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
        
        # Install Prometheus stack
        helm upgrade --install prometheus prometheus-community/kube-prometheus-stack \
            --namespace "$MONITORING_NAMESPACE" \
            --values "$SCRIPT_DIR/monitoring/prometheus-values.yaml" \
            --wait --timeout 10m
        
        # Apply ServiceMonitors and alerts
        kubectl apply -f "$SCRIPT_DIR/monitoring/servicemonitors.yaml" -n "$NAMESPACE"
        kubectl apply -f "$SCRIPT_DIR/monitoring/alertrules.yaml" -n "$NAMESPACE"
        kubectl apply -f "$SCRIPT_DIR/monitoring/grafana-dashboards-configmap.yaml" -n "$MONITORING_NAMESPACE"
        
        log_success "Monitoring stack installed"
    fi
else
    log_info "Step 10: Skipping monitoring (--skip-monitoring)"
fi
echo ""

# ============================================================
# Step 11: Final Status
# ============================================================
log_info "Step 11: Deployment complete! Getting status..."

if [ "$DRY_RUN" = false ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║                    DEPLOYMENT SUMMARY                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    
    # Get ALB URL
    echo "🌐 Application URL:"
    ALB_URL=$(kubectl get ingress frontend -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "Pending...")
    echo "   http://$ALB_URL"
    echo ""
    
    # Get Grafana URL
    echo "📊 Grafana (monitoring):"
    echo "   kubectl port-forward svc/prometheus-grafana 3000:80 -n $MONITORING_NAMESPACE"
    echo "   http://localhost:3000  (admin / postershop-monitoring)"
    echo ""
    
    # Pod status
    echo "📦 Pod Status:"
    kubectl get pods -n "$NAMESPACE" --no-headers | while read line; do
        echo "   $line"
    done
    echo ""
    
    # Secrets info
    echo "🔐 Secrets (AWS Secrets Manager):"
    echo "   - postershop/passwords - all service & DB passwords"
    echo "   - postershop/database  - database connection URLs"
    echo "   - postershop/jwt       - JWT signing secret"
    echo "   - postershop/stripe    - Stripe webhook secret"
    echo ""
    
    # Important notes
    echo "⚠️  Important:"
    echo "   - All secrets stored in AWS Secrets Manager (no local files)"
    echo "   - Secrets synced to K8s via External Secrets Operator"
    echo "   - Enable RDS deletion protection for production"
    echo "   - ALB URL may take a few minutes to become available"
    echo ""
    
    log_success "PosterShop platform is deployed!"
else
    echo ""
    log_info "DRY RUN complete. No changes were made."
fi

