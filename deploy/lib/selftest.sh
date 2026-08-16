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

echo ""
echo "=============================================="
if [ "$FAILURES" -eq 0 ]; then
    echo " PASS - $CASES checks, 0 failures"
else
    echo " FAIL - $CASES checks, $FAILURES failure(s)"
fi
echo "=============================================="
[ "$FAILURES" -eq 0 ]
