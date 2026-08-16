#!/usr/bin/env bash
# ============================================================
# PosterShop Platform - runtime config carried into helm upgrades
# ============================================================
# Sourceable helper. Defines functions only — nothing runs at source time — so
# it is safe to source into a script that already ran `set -e`. Deliberately
# does NOT set -e itself; the sourcing script owns that.
#
# Why this file exists
# --------------------
# Two settings used to be applied OUTSIDE the Helm values, by deploy.sh only:
#   * notifications EMAIL_PROVIDER/EMAIL_FROM/SES_REGION + the IRSA
#     ServiceAccount, detected from the AWS account by full-deploy.sh;
#   * payments FRONTEND_URL, patched with `kubectl set env` after the frontend
#     ingress produced an ALB hostname.
# Anything applied outside the chart's own values is invisible to the next
# `helm upgrade`. CI (.github/workflows/deploy.yaml) upgrades only the services
# whose code changed and knew nothing about either setting, so a push touching
# services/notifications reverted email delivery to `logging`, and a push
# touching services/payments restored a hostname from a dead cluster.
#
# The fix is to make Helm the owner of both values and to derive them at upgrade
# time, with precedence:
#
#     explicit environment  >  live cluster  >  chart default
#
# Deriving from the live cluster is what makes this safe for a partial deploy: a
# service that is not being upgraded is not touched at all, and a service that
# is gets handed back what it already had (or something fresher). Nothing is
# re-patched after helm, and `--reuse-values` is not used (it is banned in this
# repo — it silently resurrects values from prior releases).
#
# Usage:
#   source "$SCRIPT_DIR/lib/live-config.sh"
#   build_helm_config_args payments postershop
#   helm upgrade --install payments ./deploy/charts/payments \
#       --namespace postershop \
#       "${HELM_CONFIG_ARGS[@]+"${HELM_CONFIG_ARGS[@]}"}"
#
# The `[@]+` form is required: on bash 3.2 an empty array expands to an unbound
# variable error under `set -u`.
#
# Tested offline by deploy/lib/selftest.sh (cases CFG-1..10).
# ============================================================

# Fallback log helpers so this lib is usable (and testable) standalone. When a
# deploy script sources it the real coloured helpers are already defined and
# these definitions are skipped.
if ! declare -f log_info >/dev/null 2>&1; then
    log_info() { echo "[INFO] $1"; }
fi
if ! declare -f log_warn >/dev/null 2>&1; then
    log_warn() { echo "[WARN] $1"; }
fi
if ! declare -f log_success >/dev/null 2>&1; then
    log_success() { echo "[SUCCESS] $1"; }
fi

# Populates the global array HELM_CONFIG_ARGS with the `--set` flags that must
# accompany a `helm upgrade` of $1 in namespace $2. The array is reset on every
# call, and is EMPTY for any service that has no out-of-chart config — which is
# the normal case for seven of the ten charts.
#
# An array rather than a string on stdout: both callers then splice it into
# `helm upgrade` identically, with no quoting lost and no re-splitting.
#
# Always returns 0. An unreachable cluster, a missing namespace and a missing
# Deployment are all normal (the CI job runs before the first deploy too), and
# must yield an empty array rather than an error that fails the deploy step.
build_helm_config_args() {
    local service=$1
    local ns=$2

    HELM_CONFIG_ARGS=()

    case "$service" in
        payments)      _config_args_payments "$ns" ;;
        notifications) _config_args_notifications "$ns" ;;
        *)             : ;;   # every other chart is fully self-describing
    esac

    return 0
}

# payments: the public base URL the customer's browser returns to after Stripe
# checkout. See deploy/charts/payments/values.yaml -> frontendUrl.
_config_args_payments() {
    local ns=$1
    local url="" alb_host=""

    if [ -n "${FRONTEND_URL:-}" ]; then
        # An explicit environment value is a human override; it wins outright.
        url="${FRONTEND_URL}"
    else
        alb_host=$(_live_ingress_host frontend "$ns")
        if [ -n "$alb_host" ]; then
            # Cluster truth, and the freshest source there is. It deliberately
            # outranks whatever is currently on the Deployment: that is exactly
            # what makes a moved/re-created ALB self-heal instead of pinning the
            # dead hostname forever.
            url="http://$alb_host"
        else
            # No ingress yet (first-ever deploy, or the ALB is still
            # provisioning) — preserve whatever the running pod already has
            # rather than dropping back to the chart default.
            url=$(_live_deployment_env payments "$ns" FRONTEND_URL)
        fi
    fi

    [ -n "$url" ] && _config_add frontendUrl "$url"
    return 0
}

# notifications: the email transport. Reproduces exactly what deploy.sh applied
# inline before this lib existed, and adds the live-cluster fallback that CI
# needs — CI has no SES detection of its own and must not revert a working
# configuration just because it does not know about it.
_config_args_notifications() {
    local ns=$1
    local provider="" from="" region="" sa=""

    if [ "${EMAIL_PROVIDER:-}" = "ses" ]; then
        # full-deploy.sh detected SES (verified identity + IRSA ServiceAccount)
        # and exported these.
        provider="ses"
        from="${EMAIL_FROM:-}"
        region="${SES_REGION:-}"
        sa="${NOTIFICATIONS_SA:-}"
    elif [ "$(_live_deployment_env notifications "$ns" EMAIL_PROVIDER)" = "ses" ]; then
        provider="ses"
        from=$(_live_deployment_env notifications "$ns" EMAIL_FROM)
        region=$(_live_deployment_env notifications "$ns" SES_REGION)
        sa=$(_live_service_account notifications "$ns")
    else
        # Neither an explicit nor a live `ses` — emit nothing and let the chart
        # default (EMAIL_PROVIDER=logging) apply. That is the correct fail-safe:
        # SES without its IRSA role makes every send raise 503, which the orders
        # outbox burns five retries on per event. See the notifications chart
        # values.yaml for the full reasoning.
        return 0
    fi

    _config_add email.provider "$provider"
    [ -n "$from" ]   && _config_add email.from "$from"
    [ -n "$region" ] && _config_add email.sesRegion "$region"
    [ -n "$sa" ]     && _config_add serviceAccount.name "$sa"
    return 0
}

# Appends `--set key=value` as TWO array elements, so the value survives spaces
# and is never re-split.
#
# helm `--set` splits its argument on unescaped commas, so a value containing
# one would be silently parsed as several assignments. No value handled here can
# contain a comma (ALB hostnames, email addresses and AWS regions cannot), so
# rather than escape, refuse: dropping the flag falls back to the chart default,
# which is recoverable, whereas a mis-parsed --set writes garbage into the release.
_config_add() {
    local key=$1
    local value=$2

    case "$value" in
        *,*)
            log_warn "skipping --set $key: the value contains a comma, which helm --set cannot express"
            return 0
            ;;
    esac

    HELM_CONFIG_ARGS+=(--set "$key=$value")
    return 0
}

# Prints one env var's value from a live Deployment's first container, or
# nothing. Tolerates a missing deployment, a missing namespace and an
# unreachable cluster.
_live_deployment_env() {
    local deployment=$1
    local ns=$2
    local var=$3
    local path value

    # Assembled by concatenation because the jsonpath filter needs literal
    # double quotes around the name.
    path='{.spec.template.spec.containers[0].env[?(@.name=="'"$var"'")].value}'
    value=$(kubectl get deployment "$deployment" -n "$ns" -o "jsonpath=$path" 2>/dev/null || true)

    printf '%s' "$value"
    return 0
}

# Prints a live Deployment's serviceAccountName, or nothing.
#
# Kubernetes MATERIALISES `serviceAccountName: default` into the persisted pod
# spec even when the chart omits it, so the literal `default` carries no
# information and must be ignored. Echoing it back as
# `--set serviceAccount.name=default` would pin the pod to the wrong
# ServiceAccount and destroy the IRSA binding SES depends on.
_live_service_account() {
    local deployment=$1
    local ns=$2
    local sa

    sa=$(kubectl get deployment "$deployment" -n "$ns" \
        -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null || true)
    [ "$sa" = "default" ] && sa=""

    printf '%s' "$sa"
    return 0
}

# Prints an Ingress's provisioned load balancer hostname, or nothing (the
# ingress may not exist yet, or the ALB may still be provisioning).
_live_ingress_host() {
    local name=$1
    local ns=$2
    local host

    host=$(kubectl get ingress "$name" -n "$ns" \
        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)

    printf '%s' "$host"
    return 0
}
