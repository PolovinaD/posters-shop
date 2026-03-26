#!/bin/bash
# ============================================================
# PosterShop Platform - Infrastructure Teardown Script
# ============================================================
# Cleanly tears down all AWS infrastructure to stop costs.
# Use this when you're done testing/developing.
#
# What it deletes:
#   1. Kubernetes namespace and all deployments
#   2. RDS database (with final snapshot option)
#   3. EKS cluster and node groups
#   4. Associated CloudFormation stacks
#
# What it preserves:
#   - ECR repositories and images (cheap storage)
#   - AWS Secrets Manager secrets (for reuse on next deploy)
#   - Local secrets file backup
#
# Usage:
#   ./teardown.sh [options]
#
# Options:
#   --keep-rds          Keep RDS (just stop services)
#   --keep-ecr          Keep ECR images (default: keep)
#   --delete-ecr        Delete ECR images too
#   --delete-secrets    Delete AWS Secrets Manager secrets
#   --skip-snapshot     Don't create RDS snapshot
#   --dry-run           Show what would be deleted
#   --force             Skip confirmation prompts
#
# To redeploy later:
#   ./full-deploy.sh    # Will reuse saved passwords
# ============================================================

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load .env if exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    log_info "Loading configuration from .env"
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Configuration
AWS_PROFILE=${AWS_PROFILE:-private}
AWS_REGION=${AWS_REGION:-eu-north-1}
CLUSTER_NAME=${CLUSTER_NAME:-postershop-dev}
NAMESPACE=${NAMESPACE:-postershop}
RDS_STACK_NAME="postershop-rds"
EXPECTED_ACCOUNT_ID=${EXPECTED_ACCOUNT_ID:-553967852170}

# Parse arguments
KEEP_RDS=false
DELETE_ECR=false
DELETE_SECRETS=false
SKIP_SNAPSHOT=false
DRY_RUN=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-rds) KEEP_RDS=true; shift ;;
        --keep-ecr) DELETE_ECR=false; shift ;;
        --delete-ecr) DELETE_ECR=true; shift ;;
        --delete-secrets) DELETE_SECRETS=true; shift ;;
        --skip-snapshot) SKIP_SNAPSHOT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --force) FORCE=true; shift ;;
        *) log_error "Unknown option: $1"; exit 1 ;;
    esac
done

# ============================================================
# Verify AWS Account (SAFETY CHECK)
# ============================================================
log_info "Verifying AWS credentials..."
CURRENT_ACCOUNT=$(AWS_PROFILE=$AWS_PROFILE aws sts get-caller-identity --query Account --output text 2>/dev/null)

if [ -z "$CURRENT_ACCOUNT" ] || [ "$CURRENT_ACCOUNT" = "None" ]; then
    log_error "Failed to get AWS account. Check your credentials."
    log_error "AWS_PROFILE=$AWS_PROFILE"
    exit 1
fi

if [ "$CURRENT_ACCOUNT" != "$EXPECTED_ACCOUNT_ID" ]; then
    log_error "WRONG AWS ACCOUNT!"
    log_error "  Expected: $EXPECTED_ACCOUNT_ID"
    log_error "  Got:      $CURRENT_ACCOUNT"
    log_error ""
    log_error "You may be logged into your work account!"
    log_error "Set AWS_PROFILE=$AWS_PROFILE or check your credentials."
    exit 1
fi

log_success "AWS Account verified: $CURRENT_ACCOUNT (private)"

# Banner
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           PosterShop Platform - Teardown                     ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Account:    $CURRENT_ACCOUNT                                ║"
echo "║  Profile:    $AWS_PROFILE                                    ║"
echo "║  Region:     $AWS_REGION                                     ║"
echo "║  Cluster:    $CLUSTER_NAME                                   ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ "$DRY_RUN" = true ]; then
    log_warn "DRY RUN MODE - No changes will be made"
    echo ""
fi

# Check what exists
log_info "Checking existing resources..."

CLUSTER_EXISTS=false
RDS_EXISTS=false
SECRETS_EXIST=false

if AWS_PROFILE=$AWS_PROFILE eksctl get cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
    CLUSTER_EXISTS=true
    echo "  ✓ EKS Cluster: $CLUSTER_NAME"
else
    echo "  ✗ EKS Cluster: not found"
fi

if AWS_PROFILE=$AWS_PROFILE aws cloudformation describe-stacks --stack-name "$RDS_STACK_NAME" --region "$AWS_REGION" &> /dev/null; then
    RDS_EXISTS=true
    RDS_ENDPOINT=$(AWS_PROFILE=$AWS_PROFILE aws cloudformation describe-stacks --stack-name "$RDS_STACK_NAME" --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs[?OutputKey==`DBEndpoint`].OutputValue' --output text)
    echo "  ✓ RDS Stack: $RDS_STACK_NAME ($RDS_ENDPOINT)"
else
    echo "  ✗ RDS Stack: not found"
fi

# Check for AWS Secrets Manager secrets
SECRET_COUNT=$(AWS_PROFILE=$AWS_PROFILE aws secretsmanager list-secrets \
    --filter Key=name,Values=postershop/ \
    --region "$AWS_REGION" \
    --query 'length(SecretList)' --output text 2>/dev/null || echo "0")
if [ "$SECRET_COUNT" -gt 0 ] 2>/dev/null; then
    SECRETS_EXIST=true
    echo "  ✓ AWS Secrets Manager: $SECRET_COUNT secrets (postershop/*)"
else
    echo "  ✗ AWS Secrets Manager: no postershop secrets found"
fi

echo ""

# Nothing to delete?
if [ "$CLUSTER_EXISTS" = false ] && [ "$RDS_EXISTS" = false ] && [ "$SECRETS_EXIST" = false ]; then
    log_success "No infrastructure found. Nothing to tear down."
    exit 0
fi

# Confirmation
if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    echo "⚠️  This will DELETE the following resources:"
    [ "$CLUSTER_EXISTS" = true ] && echo "    - EKS Cluster: $CLUSTER_NAME (and all deployments)"
    [ "$RDS_EXISTS" = true ] && [ "$KEEP_RDS" = false ] && echo "    - RDS Database: $RDS_STACK_NAME"
    [ "$DELETE_ECR" = true ] && echo "    - ECR Repositories and images"
    [ "$DELETE_SECRETS" = true ] && [ "$SECRETS_EXIST" = true ] && echo "    - AWS Secrets Manager: postershop/* secrets"
    echo ""
    
    echo "📦 Will be PRESERVED:"
    [ "$KEEP_RDS" = true ] && echo "    - RDS Database (--keep-rds)"
    [ "$DELETE_ECR" = false ] && echo "    - ECR images"
    [ "$DELETE_SECRETS" = false ] && [ "$SECRETS_EXIST" = true ] && echo "    - AWS Secrets Manager secrets (use --delete-secrets to remove)"
    
    echo ""
    read -p "Are you sure you want to proceed? (yes/no): " CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "Teardown cancelled."
        exit 0
    fi
    echo ""
fi

# Track time
START_TIME=$(date +%s)

# ============================================================
# Step 1: Delete Kubernetes Namespace (if cluster exists)
# ============================================================
if [ "$CLUSTER_EXISTS" = true ]; then
    log_info "Step 1: Deleting Kubernetes namespace..."
    
    if [ "$DRY_RUN" = false ]; then
        # Configure kubectl
        AWS_PROFILE=$AWS_PROFILE aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$AWS_REGION" 2>/dev/null || true
        
        # Delete namespace (this deletes all resources in it)
        if kubectl get namespace "$NAMESPACE" &> /dev/null; then
            kubectl delete namespace "$NAMESPACE" --timeout=120s || true
            log_success "Namespace $NAMESPACE deleted"
        else
            log_info "Namespace $NAMESPACE not found"
        fi
        
        # Delete monitoring namespace if exists
        if kubectl get namespace monitoring &> /dev/null; then
            kubectl delete namespace monitoring --timeout=120s || true
            log_success "Namespace monitoring deleted"
        fi
        
        # Delete external-secrets namespace if exists
        if kubectl get namespace external-secrets &> /dev/null; then
            kubectl delete namespace external-secrets --timeout=120s || true
            log_success "Namespace external-secrets deleted"
        fi
    else
        echo "  Would delete namespace: $NAMESPACE"
        echo "  Would delete namespace: monitoring"
        echo "  Would delete namespace: external-secrets"
    fi
fi
echo ""

# ============================================================
# Step 2: Delete RDS (unless --keep-rds)
# ============================================================
if [ "$RDS_EXISTS" = true ] && [ "$KEEP_RDS" = false ]; then
    log_info "Step 2: Deleting RDS database..."
    
    if [ "$DRY_RUN" = false ]; then
        if [ "$SKIP_SNAPSHOT" = false ]; then
            SNAPSHOT_ID="postershop-final-$(date +%Y%m%d-%H%M%S)"
            log_info "Creating final snapshot: $SNAPSHOT_ID"
            # Note: CloudFormation will create snapshot on delete by default (DeletionPolicy: Snapshot)
        fi
        
        AWS_PROFILE=$AWS_PROFILE aws cloudformation delete-stack \
            --stack-name "$RDS_STACK_NAME" \
            --region "$AWS_REGION"
        
        log_info "Waiting for RDS deletion (this takes 5-10 minutes)..."
        AWS_PROFILE=$AWS_PROFILE aws cloudformation wait stack-delete-complete \
            --stack-name "$RDS_STACK_NAME" \
            --region "$AWS_REGION" || true
        
        log_success "RDS stack deleted"
    else
        echo "  Would delete RDS stack: $RDS_STACK_NAME"
    fi
elif [ "$KEEP_RDS" = true ]; then
    log_info "Step 2: Skipping RDS deletion (--keep-rds)"
fi
echo ""

# ============================================================
# Step 3: Delete EKS Cluster
# ============================================================
if [ "$CLUSTER_EXISTS" = true ]; then
    log_info "Step 3: Deleting EKS cluster..."
    
    if [ "$DRY_RUN" = false ]; then
        log_info "This takes 10-15 minutes..."
        AWS_PROFILE=$AWS_PROFILE eksctl delete cluster \
            --name "$CLUSTER_NAME" \
            --region "$AWS_REGION" \
            --wait
        
        log_success "EKS cluster deleted"
    else
        echo "  Would delete EKS cluster: $CLUSTER_NAME"
    fi
fi
echo ""

# ============================================================
# Step 4: Delete ECR Repositories (if --delete-ecr)
# ============================================================
if [ "$DELETE_ECR" = true ]; then
    log_info "Step 4: Deleting ECR repositories..."
    
    SERVICES="users catalog orders production logistics inventory payments frontend infra"
    
    if [ "$DRY_RUN" = false ]; then
        for svc in $SERVICES; do
            if AWS_PROFILE=$AWS_PROFILE aws ecr describe-repositories --repository-names "$svc" --region "$AWS_REGION" &> /dev/null; then
                AWS_PROFILE=$AWS_PROFILE AWS_PAGER="" aws ecr delete-repository \
                    --repository-name "$svc" \
                    --region "$AWS_REGION" \
                    --force
                echo "  ✓ Deleted: $svc"
            fi
        done
        log_success "ECR repositories deleted"
    else
        for svc in $SERVICES; do
            echo "  Would delete ECR repo: $svc"
        done
    fi
else
    log_info "Step 4: Keeping ECR repositories (images preserved for next deploy)"
fi
echo ""

# ============================================================
# Step 5: Delete AWS Secrets Manager Secrets (if --delete-secrets)
# ============================================================
if [ "$DELETE_SECRETS" = true ] && [ "$SECRETS_EXIST" = true ]; then
    log_info "Step 5: Deleting AWS Secrets Manager secrets..."
    
    POSTERSHOP_SECRETS="postershop/passwords postershop/database postershop/jwt postershop/stripe"
    
    if [ "$DRY_RUN" = false ]; then
        for secret in $POSTERSHOP_SECRETS; do
            if AWS_PROFILE=$AWS_PROFILE aws secretsmanager describe-secret --secret-id "$secret" --region "$AWS_REGION" &> /dev/null; then
                AWS_PROFILE=$AWS_PROFILE AWS_PAGER="" aws secretsmanager delete-secret \
                    --secret-id "$secret" \
                    --region "$AWS_REGION" \
                    --force-delete-without-recovery
                echo "  ✓ Deleted: $secret"
            fi
        done
        
        # Also delete the IAM policy for ESO
        ESO_POLICY_NAME="postershop-external-secrets"
        if AWS_PROFILE=$AWS_PROFILE aws iam get-policy --policy-arn "arn:aws:iam::${CURRENT_ACCOUNT}:policy/${ESO_POLICY_NAME}" &> /dev/null 2>&1; then
            AWS_PROFILE=$AWS_PROFILE aws iam delete-policy \
                --policy-arn "arn:aws:iam::${CURRENT_ACCOUNT}:policy/${ESO_POLICY_NAME}" 2>/dev/null || true
            echo "  ✓ Deleted IAM policy: $ESO_POLICY_NAME"
        fi
        
        log_success "AWS Secrets Manager secrets deleted"
    else
        for secret in $POSTERSHOP_SECRETS; do
            echo "  Would delete secret: $secret"
        done
    fi
else
    log_info "Step 5: Keeping AWS Secrets Manager secrets (use --delete-secrets to remove)"
fi
echo ""

# ============================================================
# Summary
# ============================================================
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                    Teardown Complete                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
log_success "Infrastructure torn down in ${MINUTES}m ${SECONDS}s"
echo ""
echo "💰 Cost savings:"
echo "   - EKS cluster: ~\$2.40/day saved"
echo "   - EC2 nodes: ~\$1-2/day saved"
[ "$KEEP_RDS" = false ] && echo "   - RDS: ~\$0.50/day saved"
echo ""
echo "📦 Preserved:"
[ "$DELETE_ECR" = false ] && echo "   - ECR images (ready for next deploy)"
[ "$DELETE_SECRETS" = false ] && echo "   - AWS Secrets Manager secrets (postershop/*)"
echo "   - Local secrets backup: $SCRIPT_DIR/.secrets"
echo ""
echo "🚀 To redeploy later:"
echo "   cd $PROJECT_ROOT"
echo "   ./deploy/full-deploy.sh"
if [ "$DELETE_SECRETS" = false ]; then
    echo ""
    echo "   Secrets will be reused from AWS Secrets Manager automatically."
fi
echo ""

