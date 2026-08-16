#!/usr/bin/env bash
# ============================================================
# PosterShop Platform - offline selftest for the deploy helper libs
# ============================================================
# Runs with NO cluster, NO AWS credentials and NO network. Every external
# command the libs call (aws, kubectl, helm) is replaced by a STUB executable in
# a temp dir that is prepended to PATH, so the tests exercise the real shell
# logic against canned responses.
#
# Usage:  bash deploy/lib/selftest.sh
# Exit:   0 = every case passed, 1 = at least one failed.
#
# `set -e` is deliberately NOT used: every case must run even after one fails,
# so the report shows all the damage at once.
# ============================================================

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$DEPLOY_DIR")"

FAILURES=0
CASES=0

ok() {
    CASES=$((CASES + 1))
    echo "  ok   $1"
}

fail() {
    CASES=$((CASES + 1))
    FAILURES=$((FAILURES + 1))
    echo "  FAIL $1"
}

assert_eq() {
    if [ "$2" = "$3" ]; then
        ok "$1"
    else
        fail "$1"
        echo "         expected: [$2]"
        echo "         actual:   [$3]"
    fi
}

assert_contains() {
    case "$3" in
        *"$2"*) ok "$1" ;;
        *)
            fail "$1"
            echo "         expected to contain: [$2]"
            echo "         actual:              [$3]"
            ;;
    esac
}

assert_not_contains() {
    case "$3" in
        *"$2"*)
            fail "$1"
            echo "         expected NOT to contain: [$2]"
            echo "         actual:                  [$3]"
            ;;
        *) ok "$1" ;;
    esac
}

for tool in jq python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "selftest: '$tool' is required but not installed" >&2
        exit 1
    fi
done

STUB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/postershop-selftest.XXXXXX")
HELM_LOG="$STUB_DIR/helm-invocations.log"
trap 'rm -rf "$STUB_DIR"' EXIT

# ------------------------------------------------------------
# STUB: aws
# Dispatches on --secret-id and prints the JSON handed to it through the
# environment. Nothing else about the AWS CLI is modelled, because nothing else
# is called on these paths.
# ------------------------------------------------------------
cat > "$STUB_DIR/aws" <<'STUB_AWS'
#!/usr/bin/env bash
# STUB - not the real AWS CLI.
empty='{}'
secret_id=""
prev=""
for arg in "$@"; do
    [ "$prev" = "--secret-id" ] && secret_id="$arg"
    prev="$arg"
done

case "$1 ${2:-}" in
    "sts get-caller-identity") echo "123456789012"; exit 0 ;;
esac

case "$secret_id" in
    postershop/stripe)    printf '%s' "${STUB_AWS_STRIPE_JSON:-$empty}" ;;
    postershop/passwords) printf '%s' "${STUB_AWS_PASSWORDS_JSON:-$empty}" ;;
    *)                    printf '%s' "$empty" ;;
esac
exit 0
STUB_AWS
chmod +x "$STUB_DIR/aws"

# ------------------------------------------------------------
# STUB: kubectl
# Models exactly the three reads live-config.sh performs. Canned answers arrive
# through the environment; STUB_KUBECTL_MISSING lists "<kind>/<name>" pairs that
# should answer NotFound, and STUB_KUBECTL_FAIL=1 simulates a cluster that
# cannot be reached at all.
# ------------------------------------------------------------
cat > "$STUB_DIR/kubectl" <<'STUB_KUBECTL'
#!/usr/bin/env bash
# STUB - not the real kubectl.
if [ "${STUB_KUBECTL_FAIL:-0}" = "1" ]; then
    echo "Unable to connect to the server: dial tcp: i/o timeout" >&2
    exit 1
fi

kind=${2:-}
name=${3:-}
jpath=""
for arg in "$@"; do
    case "$arg" in jsonpath=*) jpath="$arg" ;; esac
done

case " ${STUB_KUBECTL_MISSING:-} " in
    *" $kind/$name "*)
        echo "Error from server (NotFound): $kind \"$name\" not found" >&2
        exit 1
        ;;
esac

case "$kind/$name" in
    ingress/frontend)
        printf '%s' "${STUB_INGRESS_HOST:-}"
        ;;
    deployment/payments)
        case "$jpath" in
            *FRONTEND_URL*) printf '%s' "${STUB_PAYMENTS_FRONTEND_URL:-}" ;;
        esac
        ;;
    deployment/notifications)
        case "$jpath" in
            *EMAIL_PROVIDER*)     printf '%s' "${STUB_NOTIF_PROVIDER:-}" ;;
            *EMAIL_FROM*)         printf '%s' "${STUB_NOTIF_FROM:-}" ;;
            *SES_REGION*)         printf '%s' "${STUB_NOTIF_REGION:-}" ;;
            *serviceAccountName*) printf '%s' "${STUB_NOTIF_SA:-}" ;;
        esac
        ;;
esac
exit 0
STUB_KUBECTL
chmod +x "$STUB_DIR/kubectl"

echo "=============================================="
echo " deploy/lib selftest"
echo "=============================================="

# ============================================================
# stripe-secret.sh
# ============================================================
echo ""
echo "-- stripe-secret.sh --------------------------"

# Runs resolve_stripe_webhook_secret in an isolated subshell with stubbed AWS.
#   $1 = value of $STRIPE_WEBHOOK_SECRET in the environment ("" = unset)
#   $2 = JSON stored at postershop/stripe
#   $3 = JSON stored at postershop/passwords
# Prints everything the function emitted, plus a final machine-readable
# "RESULT:<value>|<missing-flag>" line.
#
# `set -e` is switched ON inside the subshell on purpose: full-deploy.sh runs
# under errexit, and a helper that aborts the deploy on a failed `aws` call
# would be worse than the bug being fixed.
run_resolve() {
    (
        set -e
        PATH="$STUB_DIR:$PATH"
        export PATH
        export STUB_AWS_STRIPE_JSON="$2"
        export STUB_AWS_PASSWORDS_JSON="$3"
        if [ -n "$1" ]; then
            export STRIPE_WEBHOOK_SECRET="$1"
        else
            unset STRIPE_WEBHOOK_SECRET
        fi
        # shellcheck source=deploy/lib/stripe-secret.sh
        . "$SCRIPT_DIR/stripe-secret.sh"
        resolve_stripe_webhook_secret
        echo "RESULT:$STRIPE_WEBHOOK_SECRET|$STRIPE_WEBHOOK_SECRET_MISSING"
    ) 2>&1
}

resolved_value() {
    local line
    line=$(printf '%s\n' "$1" | grep '^RESULT:' | tail -1)
    line=${line#RESULT:}
    printf '%s' "${line%|*}"
}

resolved_missing() {
    local line
    line=$(printf '%s\n' "$1" | grep '^RESULT:' | tail -1)
    printf '%s' "${line##*|}"
}

PLACEHOLDER="MISSING-run-deploy/fix-stripe-webhook-secret.sh"

# STRIPE-1: an externally supplied environment value wins over everything and
# survives untouched. This is the .env / shell path.
OUT=$(run_resolve "whsec_fromEnv" \
    '{"SECRET_KEY":"sk_test_x","WEBHOOK_SECRET":"whsec_fromStripeSecret"}' \
    '{"STRIPE_WEBHOOK_SECRET":"whsec_legacy"}')
assert_eq "STRIPE-1 env value wins"            "whsec_fromEnv" "$(resolved_value "$OUT")"
assert_eq "STRIPE-1 not reported missing"      "false"         "$(resolved_missing "$OUT")"

# STRIPE-2: with no environment value, postershop/stripe is authoritative.
OUT=$(run_resolve "" \
    '{"SECRET_KEY":"sk_test_x","WEBHOOK_SECRET":"whsec_fromStripeSecret"}' \
    '{"STRIPE_WEBHOOK_SECRET":"whsec_legacy"}')
assert_eq "STRIPE-2 postershop/stripe used"    "whsec_fromStripeSecret" "$(resolved_value "$OUT")"
assert_eq "STRIPE-2 not reported missing"      "false"                  "$(resolved_missing "$OUT")"

# STRIPE-3: legacy fallback, so an existing deploy self-heals.
OUT=$(run_resolve "" '{}' '{"STRIPE_WEBHOOK_SECRET":"whsec_legacy"}')
assert_eq "STRIPE-3 postershop/passwords fallback" "whsec_legacy" "$(resolved_value "$OUT")"
assert_eq "STRIPE-3 not reported missing"          "false"        "$(resolved_missing "$OUT")"

# STRIPE-4: nothing anywhere -> placeholder, loud warning, deploy continues.
OUT=$(run_resolve "" '{}' '{}')
assert_eq       "STRIPE-4 placeholder written"  "$PLACEHOLDER" "$(resolved_value "$OUT")"
assert_eq       "STRIPE-4 flagged missing"      "true"         "$(resolved_missing "$OUT")"
assert_contains "STRIPE-4 names the remedy"     "fix-stripe-webhook-secret.sh" "$OUT"
assert_contains "STRIPE-4 says it cannot be generated" "CANNOT be generated"   "$OUT"

# STRIPE-5: the placeholder from a previous run counts as absent, so the warning
# repeats instead of decaying into a fake success.
OUT=$(run_resolve "" "{\"WEBHOOK_SECRET\":\"$PLACEHOLDER\"}" '{}')
assert_eq "STRIPE-5 placeholder treated as absent" "true"         "$(resolved_missing "$OUT")"
assert_eq "STRIPE-5 placeholder not promoted"      "$PLACEHOLDER" "$(resolved_value "$OUT")"

# STRIPE-6: the resolver NEVER generates. Nothing it produced when it found
# nothing may look like `whsec_$(openssl rand -hex 16)`.
GENERATED_SHAPE='^whsec_[0-9a-f]{32}$'
for empty_case in "STRIPE-4" "STRIPE-5"; do
    if [ "$empty_case" = "STRIPE-4" ]; then
        OUT=$(run_resolve "" '{}' '{}')
    else
        OUT=$(run_resolve "" "{\"WEBHOOK_SECRET\":\"$PLACEHOLDER\"}" '{}')
    fi
    VAL=$(resolved_value "$OUT")
    if printf '%s' "$VAL" | grep -Eq "$GENERATED_SHAPE"; then
        fail "STRIPE-6 ($empty_case) produced a generated-looking secret: $VAL"
    else
        ok "STRIPE-6 ($empty_case) produced no generated secret"
    fi
done

# STRIPE-6b: a stored value of the generated shape is still USED (never
# rewritten) but is called out as almost certainly fake.
OUT=$(run_resolve "" '{"WEBHOOK_SECRET":"whsec_0123456789abcdef0123456789abcdef"}' '{}')
assert_eq       "STRIPE-6b generated-shape value still used" \
    "whsec_0123456789abcdef0123456789abcdef" "$(resolved_value "$OUT")"
assert_contains "STRIPE-6b generated-shape value flagged" "generated fake" "$OUT"

# ------------------------------------------------------------
# MERGE-1: the survival property, at the exact jq expression
# store_secrets_in_aws() uses (deploy/full-deploy.sh).
# ------------------------------------------------------------
EXISTING='{"SECRET_KEY":"sk_live_keep","WEBHOOK_SECRET":"whsec_realExternal"}'

# The payload the NEW code produces: whatever it resolved, which for this
# existing secret is that same real value.
OUT=$(run_resolve "" "$EXISTING" '{}')
NEW_VALUE=$(resolved_value "$OUT")
NEW_PAYLOAD=$(jq -n --arg v "$NEW_VALUE" '{WEBHOOK_SECRET: $v}')
MERGED=$(jq -s '.[0] * .[1]' <(printf '%s' "$EXISTING") <(printf '%s' "$NEW_PAYLOAD"))
assert_eq "MERGE-1 SECRET_KEY survives"    "sk_live_keep"      "$(printf '%s' "$MERGED" | jq -r '.SECRET_KEY')"
assert_eq "MERGE-1 WEBHOOK_SECRET survives byte-identical" \
    "whsec_realExternal" "$(printf '%s' "$MERGED" | jq -r '.WEBHOOK_SECRET')"

# Negative control: the OLD behaviour (payload carrying a freshly generated
# value) destroys the real one. Without this, MERGE-1 could pass for the wrong
# reason and would not have caught the original defect.
OLD_PAYLOAD='{"WEBHOOK_SECRET":"whsec_deadbeefdeadbeefdeadbeefdeadbeef"}'
MERGED_OLD=$(jq -s '.[0] * .[1]' <(printf '%s' "$EXISTING") <(printf '%s' "$OLD_PAYLOAD"))
OLD_RESULT=$(printf '%s' "$MERGED_OLD" | jq -r '.WEBHOOK_SECRET')
if [ "$OLD_RESULT" = "whsec_realExternal" ]; then
    fail "MERGE-1 negative control: generated payload should have destroyed the real value"
else
    ok "MERGE-1 negative control: generated payload destroys the real value (old bug reproduced)"
fi

# ------------------------------------------------------------
# GREP-1: the generator is gone from the tree, not just bypassed.
# This file is excluded (it necessarily contains the pattern), and comment
# lines are filtered out so the libs may keep explaining what was removed.
# ------------------------------------------------------------
whsec_generators() {
    grep -rn --exclude=selftest.sh "openssl rand" "$DEPLOY_DIR" 2>/dev/null \
        | grep -i "whsec" \
        | grep -v ':[[:space:]]*#'
}
if [ -n "$(whsec_generators)" ]; then
    fail "GREP-1 a whsec value is still generated somewhere under deploy/"
    whsec_generators
else
    ok "GREP-1 no whsec value is generated anywhere under deploy/"
fi

# ============================================================
# live-config.sh
# ============================================================
echo ""
echo "-- live-config.sh ----------------------------"

# Runs build_helm_config_args in an isolated subshell with stubbed kubectl.
#   $1 = service, $2 = namespace, remaining args = VAR=value for the stubs and
#   for the explicit-override precedence tests.
# Prints everything the function emitted plus a final "ARGS:<space-joined>" line.
# `set -e` is on inside, because both callers run under errexit.
run_config() {
    local service=$1
    local ns=$2
    shift 2
    (
        set -e
        PATH="$STUB_DIR:$PATH"
        export PATH
        for kv in "$@"; do
            export "$kv"
        done
        # shellcheck source=deploy/lib/live-config.sh
        . "$SCRIPT_DIR/live-config.sh"
        build_helm_config_args "$service" "$ns"
        echo "ARGS:${HELM_CONFIG_ARGS[@]+${HELM_CONFIG_ARGS[@]}}"
    ) 2>&1
}

config_args() {
    local line
    line=$(printf '%s\n' "$1" | grep '^ARGS:' | tail -1)
    printf '%s' "${line#ARGS:}"
}

ALB="alb-live.example.com"
# Stands in for the hostname afbc972 committed into the payments chart: a real
# ALB from a cluster that no longer exists. A stand-in rather than the literal,
# so that grepping the repo for the dead hostname keeps returning nothing.
STALE="http://k8s-postersh-frontend-deadcluster.eu-north-1.elb.amazonaws.com"

# CFG-1: payments with a live frontend ingress -> the ALB, and nothing else.
OUT=$(run_config payments postershop \
    "STUB_INGRESS_HOST=$ALB" \
    "STUB_KUBECTL_MISSING=deployment/payments")
assert_eq "CFG-1 payments takes the live ALB" \
    "--set frontendUrl=http://$ALB" "$(config_args "$OUT")"

# CFG-2: the live defect. The Deployment still carries the dead hostname from a
# previous cluster; the ingress must win so the ALB move self-heals.
OUT=$(run_config payments postershop \
    "STUB_INGRESS_HOST=$ALB" \
    "STUB_PAYMENTS_FRONTEND_URL=$STALE")
assert_eq "CFG-2 live ingress beats the stale deployment value" \
    "--set frontendUrl=http://$ALB" "$(config_args "$OUT")"
assert_not_contains "CFG-2 dead hostname not carried forward" "deadcluster" "$OUT"

# CFG-3: no ingress yet (still provisioning) -> preserve what the pod has.
OUT=$(run_config payments postershop \
    "STUB_KUBECTL_MISSING=ingress/frontend" \
    "STUB_PAYMENTS_FRONTEND_URL=http://preserved.example.com")
assert_eq "CFG-3 live deployment value preserved when no ingress" \
    "--set frontendUrl=http://preserved.example.com" "$(config_args "$OUT")"

# CFG-4: nothing at all (first-ever deploy) -> chart default, no crash.
OUT=$(run_config payments postershop \
    "STUB_KUBECTL_MISSING=ingress/frontend deployment/payments")
assert_eq "CFG-4 nothing live -> empty args" "" "$(config_args "$OUT")"

# CFG-4b: an explicit FRONTEND_URL overrides even a live ingress.
OUT=$(run_config payments postershop \
    "STUB_INGRESS_HOST=$ALB" \
    "FRONTEND_URL=http://explicit.example.com")
assert_eq "CFG-4b explicit environment override wins" \
    "--set frontendUrl=http://explicit.example.com" "$(config_args "$OUT")"

# CFG-5: notifications with full-deploy.sh's SES detection in the environment.
OUT=$(run_config notifications postershop \
    "EMAIL_PROVIDER=ses" "EMAIL_FROM=a@b.c" "SES_REGION=eu-west-1" \
    "NOTIFICATIONS_SA=notifications")
assert_eq "CFG-5 SES config from the environment" \
    "--set email.provider=ses --set email.from=a@b.c --set email.sesRegion=eu-west-1 --set serviceAccount.name=notifications" \
    "$(config_args "$OUT")"

# CFG-6: THE REGRESSION TEST for the reported CI defect. No environment hints at
# all (CI has none), a live deployment already running SES -> the whole
# configuration is reconstructed and carried through the upgrade.
OUT=$(run_config notifications postershop \
    "STUB_NOTIF_PROVIDER=ses" "STUB_NOTIF_FROM=live@example.com" \
    "STUB_NOTIF_REGION=eu-north-1" "STUB_NOTIF_SA=notifications")
assert_eq "CFG-6 SES config reconstructed from the live cluster" \
    "--set email.provider=ses --set email.from=live@example.com --set email.sesRegion=eu-north-1 --set serviceAccount.name=notifications" \
    "$(config_args "$OUT")"

# CFG-7: Kubernetes materialises serviceAccountName: default even when the chart
# omits it, so it carries no information and must never be echoed back.
OUT=$(run_config notifications postershop \
    "STUB_NOTIF_PROVIDER=ses" "STUB_NOTIF_FROM=live@example.com" \
    "STUB_NOTIF_REGION=eu-north-1" "STUB_NOTIF_SA=default")
assert_not_contains "CFG-7 literal 'default' ServiceAccount ignored" \
    "serviceAccount.name" "$(config_args "$OUT")"
assert_contains "CFG-7 the rest of the SES config still carried" \
    "email.provider=ses" "$(config_args "$OUT")"

# CFG-8: a live deployment on `logging` stays on `logging` (chart default).
OUT=$(run_config notifications postershop "STUB_NOTIF_PROVIDER=logging")
assert_eq "CFG-8 live 'logging' -> empty args" "" "$(config_args "$OUT")"

# CFG-9: every other chart is self-describing and must be left alone.
for svc in orders frontend inventory; do
    OUT=$(run_config "$svc" postershop "STUB_INGRESS_HOST=$ALB" "STUB_NOTIF_PROVIDER=ses")
    assert_eq "CFG-9 $svc -> empty args" "" "$(config_args "$OUT")"
done

# CFG-10: a totally unreachable cluster yields an empty array, not an error.
# This is the CI-before-first-deploy case and must never fail the deploy step.
OUT=$(run_config payments postershop "STUB_KUBECTL_FAIL=1")
assert_eq "CFG-10 unreachable cluster (payments) -> empty args" "" "$(config_args "$OUT")"
OUT=$(run_config notifications postershop "STUB_KUBECTL_FAIL=1")
assert_eq "CFG-10 unreachable cluster (notifications) -> empty args" "" "$(config_args "$OUT")"

# CFG-11: helm --set splits on commas, so a value containing one is refused
# rather than mis-parsed into several assignments.
OUT=$(run_config payments postershop "FRONTEND_URL=http://a.example.com,b")
assert_eq       "CFG-11 comma value not emitted" "" "$(config_args "$OUT")"
assert_contains "CFG-11 comma value is reported" "skipping --set frontendUrl" "$OUT"

# ------------------------------------------------------------
# CHART-1/2: the payments chart renders FRONTEND_URL only when told to.
# ------------------------------------------------------------
if command -v helm >/dev/null 2>&1; then
    RENDERED=$(helm template "$DEPLOY_DIR/charts/payments" --set frontendUrl=http://$ALB 2>&1)
    assert_eq "CHART-1 exactly one FRONTEND_URL when frontendUrl is set" \
        "1" "$(printf '%s\n' "$RENDERED" | grep -c 'name: FRONTEND_URL')"
    assert_contains "CHART-1 renders the value given" "http://$ALB" "$RENDERED"

    RENDERED=$(helm template "$DEPLOY_DIR/charts/payments" 2>&1)
    assert_eq "CHART-2 no FRONTEND_URL by default" \
        "0" "$(printf '%s\n' "$RENDERED" | grep -c 'name: FRONTEND_URL')"
else
    echo "  skip helm chart render checks (helm not installed)"
fi

# ------------------------------------------------------------
# GREP-2: no ALB hostname may be committed to any chart. This is the mistake
# afbc972 made and the reason the frontendUrl scalar exists.
# ------------------------------------------------------------
if grep -rn "elb.amazonaws.com" "$DEPLOY_DIR/charts" >/dev/null 2>&1; then
    fail "GREP-2 an ALB hostname is hardcoded under deploy/charts/"
    grep -rn "elb.amazonaws.com" "$DEPLOY_DIR/charts"
else
    ok "GREP-2 no ALB hostname hardcoded under deploy/charts/"
fi

# ============================================================
# deploy.sh end-to-end, fully stubbed
# ============================================================
echo ""
echo "-- deploy.sh (stubbed --dry-run) -------------"

# helm STUB: records every invocation and succeeds.
cat > "$STUB_DIR/helm" <<'STUB_HELM'
#!/usr/bin/env bash
# STUB - not the real helm.
printf '%s\n' "$*" >> "$STUB_HELM_LOG"
exit 0
STUB_HELM
chmod +x "$STUB_DIR/helm"

# deploy.sh sources $PROJECT_ROOT/.env, and a developer's real .env would make
# this test's result depend on their machine. Run it from a throwaway tree that
# contains only what the script needs, and no .env.
FAKE_ROOT="$STUB_DIR/repo"
mkdir -p "$FAKE_ROOT/deploy"
cp "$DEPLOY_DIR/deploy.sh" "$FAKE_ROOT/deploy/deploy.sh"
cp -R "$SCRIPT_DIR" "$FAKE_ROOT/deploy/lib"
cp -R "$DEPLOY_DIR/charts" "$FAKE_ROOT/deploy/charts"

: > "$HELM_LOG"
DEPLOY_OUT=$(
    PATH="$STUB_DIR:$PATH" \
    STUB_HELM_LOG="$HELM_LOG" \
    STUB_INGRESS_HOST="$ALB" \
    STUB_PAYMENTS_FRONTEND_URL="$STALE" \
    STUB_NOTIF_PROVIDER=ses \
    STUB_NOTIF_FROM=live@example.com \
    STUB_NOTIF_REGION=eu-north-1 \
    STUB_NOTIF_SA=notifications \
    AWS_ACCOUNT_ID=123456789012 \
    bash "$FAKE_ROOT/deploy/deploy.sh" postershop --dry-run 2>&1
)
DEPLOY_RC=$?

assert_eq "DEPLOY-1 stubbed deploy.sh exits 0" "0" "$DEPLOY_RC"

helm_line_for() {
    grep -- "--install $1 " "$HELM_LOG" 2>/dev/null | tail -1
}

assert_contains "DEPLOY-2 payments gets the live ALB" \
    "frontendUrl=http://$ALB" "$(helm_line_for payments)"
assert_not_contains "DEPLOY-2 payments does not get the stale hostname" \
    "deadcluster" "$(helm_line_for payments)"
assert_contains "DEPLOY-3 notifications keeps SES from the live cluster" \
    "email.provider=ses" "$(helm_line_for notifications)"
assert_contains "DEPLOY-3 notifications keeps its IRSA ServiceAccount" \
    "serviceAccount.name=notifications" "$(helm_line_for notifications)"
assert_not_contains "DEPLOY-4 orders gets no frontendUrl" \
    "frontendUrl" "$(helm_line_for orders)"
assert_not_contains "DEPLOY-4 orders gets no email config" \
    "email.provider" "$(helm_line_for orders)"
assert_contains "DEPLOY-5 the SES decision is still echoed to the operator" \
    "real email via SES" "$DEPLOY_OUT"

# Every chart must still be upgraded with its ECR image, untouched by this change.
UPGRADES=$(grep -c -- "--install" "$HELM_LOG")
WITH_IMAGE=$(grep -c -- "--set image.repository=" "$HELM_LOG")
assert_eq "DEPLOY-6 every helm upgrade still sets image.repository" "$UPGRADES" "$WITH_IMAGE"
if [ "$UPGRADES" -ge 10 ]; then
    ok "DEPLOY-6 all $UPGRADES charts upgraded"
else
    fail "DEPLOY-6 only $UPGRADES charts upgraded, expected at least 10"
fi

# ============================================================
# CI workflow
# ============================================================
echo ""
echo "-- .github/workflows/deploy.yaml -------------"

WORKFLOW="$REPO_ROOT/.github/workflows/deploy.yaml"

if python3 -c "import yaml" >/dev/null 2>&1; then
    if python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$WORKFLOW" >/dev/null 2>&1; then
        ok "WF-1 workflow YAML parses"
    else
        fail "WF-1 workflow YAML does not parse"
        python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$WORKFLOW"
    fi
else
    echo "  skip WF-1 (PyYAML not installed)"
fi

if grep -q "deploy/lib/live-config.sh" "$WORKFLOW"; then
    ok "WF-2 workflow sources the shared helper"
else
    fail "WF-2 workflow does not source deploy/lib/live-config.sh"
fi

if grep -q "build_helm_config_args" "$WORKFLOW" && grep -q 'HELM_CONFIG_ARGS\[@\]' "$WORKFLOW"; then
    ok "WF-3 workflow calls the helper and splices its args into helm upgrade"
else
    fail "WF-3 workflow does not use HELM_CONFIG_ARGS in helm upgrade"
fi

# GREP-3: --reuse-values is banned. This file is excluded and comment lines are
# filtered, so both the lib and the workflow may keep saying so out loud.
reuse_values_uses() {
    grep -rn --exclude=selftest.sh -- "--reuse-values" \
        "$DEPLOY_DIR" "$REPO_ROOT/.github/workflows" 2>/dev/null \
        | grep -v ':[[:space:]]*#'
}
if [ -n "$(reuse_values_uses)" ]; then
    fail "GREP-3 --reuse-values is used somewhere"
    reuse_values_uses
else
    ok "GREP-3 --reuse-values is not used anywhere"
fi

echo ""
echo "=============================================="
if [ "$FAILURES" -eq 0 ]; then
    echo " PASS - $CASES checks, 0 failures"
else
    echo " FAIL - $CASES checks, $FAILURES failure(s)"
fi
echo "=============================================="
[ "$FAILURES" -eq 0 ]
