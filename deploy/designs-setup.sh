#!/bin/bash
# ============================================================
# PosterShop — one-time S3 + IRSA setup for the designs service
# ============================================================
# Provisions the production half of the designs image storage (AIP-05): a
# private S3 bucket for generated poster images, a least-privilege IAM policy
# (s3:PutObject + s3:GetObject on that bucket only) and an IRSA-annotated
# `designs` ServiceAccount so the pod gets credentials from the pod-identity
# webhook instead of a stored key.
#
# Deliberately NOT part of full-deploy.sh:
#   - it is one-time account setup, not per-deploy work; the bucket and the IAM
#     policy survive cluster teardowns (teardown.sh only removes the bucket when
#     asked with --delete-bucket)
#   - the ServiceAccount half needs a running cluster, the bucket half does not,
#     and the two are re-run independently
#
# full-deploy.sh instead DETECTS the result of this script (bucket exists AND
# the ServiceAccount carries an eks.amazonaws.com/role-arn annotation) and
# switches the designs chart to STORAGE_BACKEND=s3 only once both are in place.
# Until then the chart's default applies: images live on an emptyDir and are
# LOST on every pod restart — fine for a demo, not for printed products.
#
# Usage:
#   ./deploy/designs-setup.sh [--bucket <name>] [--region <aws-region>]
#
# Defaults: bucket postershop-designs-<account-id> (DESIGNS_S3_BUCKET), region
# DESIGNS_S3_REGION > AWS_REGION > eu-north-1. Everything here is idempotent:
# safe to re-run.
# ============================================================
set -euo pipefail

export AWS_PAGER=""

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
[ -f "$PROJECT_ROOT/.env" ] && { set -a; . "$PROJECT_ROOT/.env"; set +a; }

CLUSTER_NAME="${CLUSTER_NAME:-postershop}"
NAMESPACE="${NAMESPACE:-postershop}"
AWS_REGION="${AWS_REGION:-eu-north-1}"
# The bucket region defaults to the cluster region so one region covers
# everything; S3 is global by name but regional by placement, and keeping them
# equal avoids cross-region data transfer on every image read.
REGION="${DESIGNS_S3_REGION:-$AWS_REGION}"
BUCKET_ARG=""
SA_NAME="designs"
POLICY_NAME="postershop-designs-s3"

while [ $# -gt 0 ]; do
    case "$1" in
        --bucket) BUCKET_ARG="$2"; shift 2 ;;
        --region) REGION="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--bucket <name>] [--region <aws-region>]"
            exit 0 ;;
        *) log_error "Unknown option: $1"; echo "Usage: $0 [--bucket <name>] [--region <aws-region>]"; exit 1 ;;
    esac
done

for c in aws jq; do
    command -v "$c" &> /dev/null || { log_error "$c is required"; exit 1; }
done
aws sts get-caller-identity &> /dev/null || { log_error "AWS credentials not configured"; exit 1; }
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Resolved after the account is known: the default bucket name embeds it so
# the (globally unique) name cannot collide with another account's.
BUCKET="${BUCKET_ARG:-${DESIGNS_S3_BUCKET:-postershop-designs-${AWS_ACCOUNT_ID}}}"

echo "════════════════════════════════════════════════════════════"
echo "  designs S3/IRSA setup — bucket: $BUCKET   region: $REGION"
echo "════════════════════════════════════════════════════════════"
echo ""
log_info "AWS account: $AWS_ACCOUNT_ID"
echo ""

# ── 1. Bucket ───────────────────────────────────────────────────────────────
log_info "Step 1: S3 bucket"
if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" &> /dev/null; then
    log_success "  bucket $BUCKET already exists — nothing to do"
else
    log_info "  creating bucket $BUCKET in $REGION ..."
    # LocationConstraint is required for every region except us-east-1, where
    # passing it is an error.
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" > /dev/null
    else
        aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION" > /dev/null
    fi
    log_success "  bucket created"
fi
# The service proxies every image through GET /images/{key}; nothing reads the
# bucket directly, so it stays fully private. Idempotent.
aws s3api put-public-access-block --bucket "$BUCKET" --region "$REGION" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
log_info "  public access blocked (the designs service proxies every image)"
BUCKET_READY=true
echo ""

# ── 2. IAM policy ───────────────────────────────────────────────────────────
log_info "Step 2: least-privilege IAM policy $POLICY_NAME"
POLICY_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:policy/${POLICY_NAME}"
if aws iam get-policy --policy-arn "$POLICY_ARN" &> /dev/null; then
    log_info "  policy $POLICY_NAME exists"
else
    log_info "  creating policy $POLICY_NAME (s3:PutObject + s3:GetObject on $BUCKET/* only)"
    aws iam create-policy --policy-name "$POLICY_NAME" --policy-document "{
  \"Version\": \"2012-10-17\",
  \"Statement\": [{\"Effect\": \"Allow\", \"Action\": [\"s3:PutObject\", \"s3:GetObject\"], \"Resource\": \"arn:aws:s3:::${BUCKET}/*\"}]
}" > /dev/null
    log_success "  policy created"
fi
echo ""

# ── 3. IRSA ServiceAccount ──────────────────────────────────────────────────
log_info "Step 3: IRSA ServiceAccount $NAMESPACE/$SA_NAME"
if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
    log_warn "  cluster '$CLUSTER_NAME' not reachable — skipping ServiceAccount creation."
    log_warn "  Re-run this script once the cluster is up; steps 1 and 2 already persist."
    SA_READY=false
else
    if kubectl get sa "$SA_NAME" -n "$NAMESPACE" &> /dev/null && \
       [ -n "$(kubectl get sa "$SA_NAME" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.eks\.amazonaws\.com/role-arn}' 2>/dev/null)" ]; then
        log_success "  ServiceAccount $NAMESPACE/$SA_NAME already bound to an IAM role"
    else
        command -v eksctl &> /dev/null || { log_error "eksctl is required for this step"; exit 1; }
        log_info "  creating IAM service account (this takes ~1 minute)"
        eksctl create iamserviceaccount \
            --name "$SA_NAME" --namespace "$NAMESPACE" \
            --cluster "$CLUSTER_NAME" --region "$AWS_REGION" \
            --attach-policy-arn "$POLICY_ARN" \
            --override-existing-serviceaccounts --approve
        log_success "  ServiceAccount created and annotated"
    fi
    SA_READY=true
fi
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════"
if [ "$BUCKET_READY" = true ] && [ "${SA_READY:-false}" = true ]; then
    log_success "designs S3/IRSA setup complete."
    echo ""
    echo "  full-deploy.sh will now detect this and deploy designs with"
    echo "  STORAGE_BACKEND=s3 automatically. To apply it without a full deploy:"
    echo ""
    echo "    helm upgrade --install designs deploy/charts/designs \\"
    echo "      --namespace $NAMESPACE \\"
    echo "      --set image.repository=<ecr>/designs \\"
    echo "      --set serviceAccount.name=$SA_NAME \\"
    echo "      --set storage.backend=s3 \\"
    echo "      --set storage.bucket=$BUCKET \\"
    echo "      --set storage.region=$REGION"
    echo ""
    echo "  Images already on the pod's emptyDir are NOT migrated; only new"
    echo "  generations land in S3."
else
    log_warn "designs S3/IRSA setup is NOT complete yet."
    [ "${SA_READY:-false}" != true ] && echo "  ▸ bring the cluster up, then re-run this script"
    echo ""
    echo "  Until both halves exist, designs stays on STORAGE_BACKEND=local (an"
    echo "  emptyDir), where generated images are lost on every pod restart."
fi
echo "════════════════════════════════════════════════════════════"
