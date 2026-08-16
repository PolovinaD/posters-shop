#!/usr/bin/env bash
# One-shot repair: put the REAL Stripe webhook signing secret into AWS Secrets
# Manager and roll the pods that consume it.
#
# Why this exists: full-deploy.sh generated STRIPE_WEBHOOK_SECRET with
# `openssl rand -hex 16`. A webhook signing secret is ISSUED BY STRIPE — a
# generated value can never validate a real signature, so every incoming
# Stripe webhook fails with HTTP 400 "No signatures found matching the
# expected signature for payload" and paid orders never leave `reserved`.
#
# Usage:
#   ./deploy/fix-stripe-webhook-secret.sh whsec_xxxxxxxxxxxxxxxx
#
# The value comes from the Stripe Dashboard:
#   Developers -> Webhooks -> <your endpoint> -> Signing secret -> Reveal
# The Stripe API does NOT return it after endpoint creation.
set -euo pipefail

export AWS_PAGER=""
REGION="${AWS_REGION:-eu-north-1}"
PROFILE="${AWS_PROFILE:-private}"
NAMESPACE="${NAMESPACE:-postershop}"
SECRET_ID="postershop/stripe"

WEBHOOK_SECRET="${1:-}"
if [ -z "$WEBHOOK_SECRET" ]; then
    echo "usage: $0 whsec_..." >&2
    exit 1
fi
case "$WEBHOOK_SECRET" in
    whsec_*) ;;
    *) echo "error: a Stripe signing secret starts with 'whsec_'" >&2; exit 1 ;;
esac

echo "==> account check"
aws sts get-caller-identity --profile "$PROFILE" --query Account --output text

# Merge, never replace: postershop/stripe also holds SECRET_KEY, a real Stripe
# API key no script can regenerate. put-secret-value replaces the whole value,
# so read-modify-write is mandatory here.
echo "==> merging WEBHOOK_SECRET into $SECRET_ID (preserving SECRET_KEY)"
CURRENT=$(aws secretsmanager get-secret-value --secret-id "$SECRET_ID" \
    --region "$REGION" --profile "$PROFILE" --query SecretString --output text)

MERGED=$(WEBHOOK_SECRET="$WEBHOOK_SECRET" python3 -c '
import json, os, sys
d = json.loads(sys.stdin.read())
d["WEBHOOK_SECRET"] = os.environ["WEBHOOK_SECRET"]
missing = [k for k in ("SECRET_KEY",) if not d.get(k)]
if missing:
    print("WARNING: %s absent from the secret" % ", ".join(missing), file=sys.stderr)
sys.stdout.write(json.dumps(d))
' <<< "$CURRENT")

aws secretsmanager put-secret-value --secret-id "$SECRET_ID" \
    --region "$REGION" --profile "$PROFILE" \
    --secret-string "$MERGED" >/dev/null
echo "    stored"

# ExternalSecrets caches for an hour; force an immediate re-sync instead of waiting.
echo "==> forcing ExternalSecret re-sync"
kubectl annotate externalsecret postershop-stripe -n "$NAMESPACE" \
    force-sync="$(date +%s)" --overwrite >/dev/null 2>&1 \
    || echo "    (no postershop-stripe ExternalSecret found — check the name)"

for i in $(seq 1 30); do
    LIVE=$(kubectl get secret postershop-stripe -n "$NAMESPACE" \
        -o jsonpath='{.data.WEBHOOK_SECRET}' 2>/dev/null | base64 -d || true)
    [ "$LIVE" = "$WEBHOOK_SECRET" ] && { echo "    k8s secret now matches"; break; }
    sleep 2
done

echo "==> restarting consumers so they pick up the new value"
kubectl rollout restart deployment/orders deployment/payments -n "$NAMESPACE"
kubectl rollout status deployment/orders -n "$NAMESPACE" --timeout=180s

echo
echo "Done. Now hit 'Resend' on the failed event in the Stripe Dashboard"
echo "(Developers -> Webhooks -> endpoint -> Events), or just wait — Stripe"
echo "retries failed deliveries for up to 3 days."
