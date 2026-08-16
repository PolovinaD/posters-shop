#!/bin/bash
# ============================================================
# PosterShop — one-time SES setup for real email delivery
# ============================================================
# Does every part of enabling AWS SES that CAN be automated, and stops cleanly
# at the one part that cannot: clicking the confirmation link SES emails you.
# That click is the proof-of-control mechanism itself, so a script that could
# perform it would defeat the point of verification.
#
# Deliberately NOT part of full-deploy.sh:
#   - it is one-time account setup, not per-deploy work; verification survives
#     cluster teardowns, so re-running it on every deploy just re-sends mail
#   - it would block an unattended deploy waiting on a human inbox
#   - enabling SES before the identity is confirmed is worse than not enabling
#     it: every send raises, notifications answers 503, and the orders outbox
#     burns all five retries per event before abandoning it (there is no DLQ)
#
# full-deploy.sh instead DETECTS the result of this script and switches the
# notifications chart to EMAIL_PROVIDER=ses only once both halves are in place.
#
# Usage:
#   ./deploy/ses-setup.sh you@gmail.com [--region eu-north-1]
#
# Everything here is idempotent: safe to re-run.
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

EMAIL="${1:-${EMAIL_FROM:-}}"
# Default to the cluster's own region so one region covers everything. SES
# identities are regional and need not match the workload region, but keeping
# them equal removes a whole class of "verified in the wrong region" confusion.
SES_REGION="${SES_REGION:-${AWS_REGION:-eu-north-1}}"
CLUSTER_NAME="${CLUSTER_NAME:-postershop}"
NAMESPACE="${NAMESPACE:-postershop}"
AWS_REGION="${AWS_REGION:-eu-north-1}"
SA_NAME="notifications"
POLICY_NAME="postershop-notifications-ses"

while [ $# -gt 0 ]; do
    case "$1" in
        --region) SES_REGION="$2"; shift 2 ;;
        *) shift ;;
    esac
done

if [ -z "$EMAIL" ]; then
    log_error "Usage: $0 <email-address> [--region <ses-region>]"
    log_error "The address is used as BOTH the SES sender identity (EMAIL_FROM) and,"
    log_error "while the account is in sandbox, must also be verified as a recipient."
    exit 1
fi

echo "════════════════════════════════════════════════════════════"
echo "  SES setup — identity: $EMAIL   region: $SES_REGION"
echo "════════════════════════════════════════════════════════════"
echo ""

for c in aws jq; do
    command -v "$c" &> /dev/null || { log_error "$c is required"; exit 1; }
done
aws sts get-caller-identity &> /dev/null || { log_error "AWS credentials not configured"; exit 1; }
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
log_info "AWS account: $ACCOUNT_ID"
echo ""

# ── 1. Sender identity ──────────────────────────────────────────────────────
log_info "Step 1: SES identity"
STATUS=$(aws ses get-identity-verification-attributes \
    --identities "$EMAIL" --region "$SES_REGION" \
    --query "VerificationAttributes.\"$EMAIL\".VerificationStatus" \
    --output text 2>/dev/null || echo "None")

case "$STATUS" in
    Success)
        log_success "  $EMAIL is already verified in $SES_REGION — nothing to do"
        VERIFIED=true ;;
    Pending)
        log_warn "  $EMAIL is PENDING: SES has sent a confirmation link, it is not clicked yet"
        log_warn "  Confirmation links expire 24h after they are issued."
        VERIFIED=false ;;
    *)
        log_info "  requesting verification for $EMAIL ..."
        aws ses verify-email-identity --email-address "$EMAIL" --region "$SES_REGION"
        log_warn "  SES has emailed a confirmation link to $EMAIL — open it to finish."
        VERIFIED=false ;;
esac
echo ""

# ── 2. Sandbox status ───────────────────────────────────────────────────────
log_info "Step 2: account sending mode"
PROD_ACCESS=$(aws sesv2 get-account --region "$SES_REGION" \
    --query 'ProductionAccessEnabled' --output text 2>/dev/null || echo "unknown")
QUOTA=$(aws sesv2 get-account --region "$SES_REGION" \
    --query 'SendQuota.Max24HourSend' --output text 2>/dev/null || echo "?")
if [ "$PROD_ACCESS" = "True" ]; then
    log_success "  production access enabled — may send to any recipient (quota ${QUOTA}/24h)"
else
    log_warn "  SANDBOX mode (quota ${QUOTA}/24h): SES will only deliver to VERIFIED addresses."
    log_warn "  Recipients are taken from the order's customer_email, which"
    log_warn "  services/orders/main.py sets from the JWT subject — so the logged-in user"
    log_warn "  IS the recipient. Place the test order as a user whose address is verified"
    log_warn "  (using $EMAIL for both roles is the simplest option)."
fi
echo ""

# ── 3. IRSA role ────────────────────────────────────────────────────────────
log_info "Step 3: IRSA role for ses:SendEmail"
if ! aws eks describe-cluster --name "$CLUSTER_NAME" --region "$AWS_REGION" &> /dev/null; then
    log_warn "  cluster '$CLUSTER_NAME' not reachable — skipping ServiceAccount creation."
    log_warn "  Re-run this script once the cluster is up; steps 1 and 2 already persist."
    SA_READY=false
else
    POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"
    if aws iam get-policy --policy-arn "$POLICY_ARN" &> /dev/null; then
        log_info "  policy $POLICY_NAME exists"
    else
        log_info "  creating least-privilege policy $POLICY_NAME (ses:SendEmail only)"
        aws iam create-policy --policy-name "$POLICY_NAME" --policy-document '{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Action": ["ses:SendEmail", "ses:SendRawEmail"], "Resource": "*"}]
}' > /dev/null
    fi

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
if [ "$VERIFIED" = true ] && [ "${SA_READY:-false}" = true ]; then
    log_success "SES setup complete."
    echo ""
    echo "  full-deploy.sh will now detect this and deploy notifications with"
    echo "  EMAIL_PROVIDER=ses automatically. To apply it without a full deploy:"
    echo ""
    echo "    helm upgrade --install notifications deploy/charts/notifications \\"
    echo "      --namespace $NAMESPACE \\"
    echo "      --set image.repository=<ecr>/notifications \\"
    echo "      --set serviceAccount.name=$SA_NAME \\"
    echo "      --set email.provider=ses \\"
    echo "      --set email.from=$EMAIL \\"
    echo "      --set email.sesRegion=$SES_REGION"
else
    log_warn "SES setup is NOT complete yet."
    [ "$VERIFIED" != true ] && echo "  ▸ open the confirmation link SES sent to $EMAIL, then re-run this script"
    [ "${SA_READY:-false}" != true ] && echo "  ▸ bring the cluster up, then re-run this script"
    echo ""
    echo "  Until both are done, notifications stays on EMAIL_PROVIDER=logging,"
    echo "  which renders mail into the pod log and needs no AWS access."
fi
echo "════════════════════════════════════════════════════════════"
