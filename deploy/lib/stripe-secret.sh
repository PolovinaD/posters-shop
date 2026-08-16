#!/usr/bin/env bash
# ============================================================
# PosterShop Platform - Stripe webhook signing secret resolution
# ============================================================
# Sourceable helper. Defines constants and functions only — nothing runs at
# source time — so it is safe to source into a script that already ran `set -e`.
# Deliberately does NOT set -e itself; the sourcing script owns that.
#
# Why this file exists
# --------------------
# full-deploy.sh used to do `STRIPE_WEBHOOK_SECRET="whsec_$(openssl rand -hex 16)"`.
# A Stripe webhook SIGNING secret is ISSUED BY STRIPE and cannot be generated:
# it is the HMAC key Stripe signs the delivery with. A generated value can never
# validate a real signature, so `stripe.Webhook.construct_event()`
# (services/orders/stripe_webhook.py) rejects every delivery with HTTP 400 and
# paid orders stay `reserved` forever.
#
# So this helper only ever LOOKS the value up. It never invents one. When it
# finds nothing it says so loudly and falls back to a self-describing
# placeholder (see WHSEC_PLACEHOLDER below), then lets the deploy continue.
#
# Usage:
#   source "$SCRIPT_DIR/lib/stripe-secret.sh"
#   resolve_stripe_webhook_secret
#   export STRIPE_WEBHOOK_SECRET       # set by the call above
#   # $STRIPE_WEBHOOK_SECRET_MISSING is "true" when nothing real was found
#
# Tested offline by deploy/lib/selftest.sh (cases STRIPE-1..6, MERGE-1).
# ============================================================

# The value written when no real signing secret can be found anywhere.
#
# It is NOT the empty string and the key is NOT omitted, deliberately:
# deploy/secrets/external-secrets.yaml requires the `WEBHOOK_SECRET` property to
# exist in postershop/stripe. Without it the ExternalSecret never produces the
# postershop-stripe Kubernetes Secret at all — which takes SECRET_KEY down with
# it and leaves the `payments` and `orders` pods in CreateContainerConfigError.
# A missing Stripe credential would become a total outage.
#
# It also deliberately does NOT start with `whsec_`, so it can never be mistaken
# for a real credential, it names its own remedy in any log line that prints it,
# and resolve_stripe_webhook_secret() treats it as "absent" on the next run so
# the warning repeats instead of decaying into a fake success.
WHSEC_PLACEHOLDER="MISSING-run-deploy/fix-stripe-webhook-secret.sh"

# Fallback log helpers so this lib is usable (and testable) standalone. When
# full-deploy.sh sources it the real coloured helpers are already defined and
# these definitions are skipped. `declare -f` is used rather than `type` because
# it is unambiguous about functions specifically and works on bash 3.2.
if ! declare -f log_info >/dev/null 2>&1; then
    log_info() { echo "[INFO] $1"; }
fi
if ! declare -f log_warn >/dev/null 2>&1; then
    log_warn() { echo "[WARN] $1"; }
fi
if ! declare -f log_success >/dev/null 2>&1; then
    log_success() { echo "[SUCCESS] $1"; }
fi

# Resolves the Stripe webhook signing secret into the global
# STRIPE_WEBHOOK_SECRET, and reports whether a real one was found in the global
# STRIPE_WEBHOOK_SECRET_MISSING ("true"/"false").
#
# Precedence, first real value wins:
#   1. $STRIPE_WEBHOOK_SECRET already in the environment (.env or an export) —
#      a human put it there, so it is authoritative.
#   2. postershop/stripe -> WEBHOOK_SECRET — the authoritative store. This is
#      where the ExternalSecret reads and where deploy/fix-stripe-webhook-secret.sh
#      writes, so anyone who already ran the repair gets no warning.
#   3. postershop/passwords -> STRIPE_WEBHOOK_SECRET — the legacy location the
#      old code used, kept so an existing deploy self-heals into (2).
#   4. nothing -> WHSEC_PLACEHOLDER plus a loud warning. Never generated.
#
# Always returns 0: a missing Stripe credential must not abort a deploy of a
# cluster that is routinely torn down and re-raised, and a demo that never
# touches Stripe should not be blocked by it.
resolve_stripe_webhook_secret() {
    local value="" origin=""

    STRIPE_WEBHOOK_SECRET_MISSING=false

    if _stripe_secret_is_real "${STRIPE_WEBHOOK_SECRET:-}"; then
        value="${STRIPE_WEBHOOK_SECRET}"
        origin="the environment (.env or an exported variable)"
    fi

    if [ -z "$value" ]; then
        local from_stripe
        from_stripe=$(_stripe_secret_from_aws "postershop/stripe" "WEBHOOK_SECRET")
        if _stripe_secret_is_real "$from_stripe"; then
            value="$from_stripe"
            origin="AWS Secrets Manager postershop/stripe -> WEBHOOK_SECRET"
        fi
    fi

    if [ -z "$value" ]; then
        local from_passwords
        from_passwords=$(_stripe_secret_from_aws "postershop/passwords" "STRIPE_WEBHOOK_SECRET")
        if _stripe_secret_is_real "$from_passwords"; then
            value="$from_passwords"
            origin="AWS Secrets Manager postershop/passwords -> STRIPE_WEBHOOK_SECRET (legacy location)"
        fi
    fi

    if [ -z "$value" ]; then
        STRIPE_WEBHOOK_SECRET="$WHSEC_PLACEHOLDER"
        STRIPE_WEBHOOK_SECRET_MISSING=true
        log_warn "No Stripe webhook signing secret found (checked: \$STRIPE_WEBHOOK_SECRET,"
        log_warn "  postershop/stripe -> WEBHOOK_SECRET, postershop/passwords -> STRIPE_WEBHOOK_SECRET)."
        log_warn "  A signing secret is ISSUED BY STRIPE and CANNOT be generated, so this"
        log_warn "  script will not invent one. Stripe webhook signature verification WILL"
        log_warn "  fail (HTTP 400) and paid orders will stay in 'reserved'."
        log_warn "  Get the value from the Stripe Dashboard:"
        log_warn "    Developers -> Webhooks -> <your endpoint> -> Signing secret -> Reveal"
        log_warn "  Then run:  ./deploy/fix-stripe-webhook-secret.sh whsec_..."
        log_warn "  Writing the placeholder '$WHSEC_PLACEHOLDER' so the ExternalSecret keeps"
        log_warn "  syncing and the payments/orders pods keep starting. Deployment continues."
        return 0
    fi

    STRIPE_WEBHOOK_SECRET="$value"
    log_success "Stripe webhook signing secret found in $origin"
    _stripe_warn_if_suspicious "$value"
    return 0
}

# Warns about a value that was found but looks wrong. Never rejects it and never
# rewrites it — only the human who holds the Stripe Dashboard can settle this,
# and refusing to deploy over a heuristic would be worse than deploying with a
# warning.
_stripe_warn_if_suspicious() {
    local value=$1

    case "$value" in
        whsec_*) ;;
        *)
            log_warn "  ...but it does not start with 'whsec_', so it does not look like a"
            log_warn "     Stripe signing secret. Verify it in the Stripe Dashboard."
            return 0
            ;;
    esac

    # Exactly 32 lowercase hex characters after the prefix is byte-for-byte what
    # the deleted `whsec_$(openssl rand -hex 16)` produced, so a value of this
    # shape is almost certainly a leftover generated fake still sitting in AWS.
    # A real Stripe signing secret is a longer mixed-case base62-ish string, so
    # the false-positive probability here is negligible — do NOT "fix" this
    # heuristic into something looser, and do NOT make it fatal.
    if [[ $value =~ ^whsec_[0-9a-f]{32}$ ]]; then
        log_warn "  ...but its shape is exactly what the old 'openssl rand -hex 16' code"
        log_warn "     generated (whsec_ + 32 lowercase hex). It is almost certainly a"
        log_warn "     generated fake, not a real Stripe signing secret. Replace it with"
        log_warn "     ./deploy/fix-stripe-webhook-secret.sh whsec_..."
    fi

    return 0
}

# Reads one key out of one AWS Secrets Manager secret. Prints the value, or
# nothing. Tolerates a missing secret, missing credentials, and a value that is
# not JSON — every failure yields the empty string rather than a non-zero exit,
# because callers run under `set -e`.
_stripe_secret_from_aws() {
    local secret_id=$1
    local key=$2
    local json value

    json=$(aws secretsmanager get-secret-value \
        --secret-id "$secret_id" \
        --region "${AWS_REGION:-eu-north-1}" \
        --query SecretString --output text 2>/dev/null || echo '{}')
    [ -z "$json" ] && json='{}'

    value=$(printf '%s' "$json" | jq -r --arg k "$key" '.[$k] // empty' 2>/dev/null || true)
    printf '%s' "$value"
    return 0
}

# True when $1 is a usable secret: non-empty and not our own placeholder.
# Treating the placeholder as absent is what makes the warning repeat on every
# run until the real value is supplied.
_stripe_secret_is_real() {
    local value=${1:-}

    [ -n "$value" ] || return 1
    [ "$value" != "$WHSEC_PLACEHOLDER" ] || return 1
    return 0
}
