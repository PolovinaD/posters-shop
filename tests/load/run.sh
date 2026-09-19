#!/usr/bin/env bash
# Stepped load test: 4 VU levels x 2 paths, one k6 run per step, summary JSON per step,
# and a replica sampler (orders/catalog deployments + HPAs) every 10 s.
# Usage: run.sh <BASE_URL> <OUT_DIR> [STEP_DURATION=90s] [VUS="10 50 100 200"]
set -euo pipefail
BASE=$1; OUT=$2; DUR=${3:-90s}; VUS=${4:-"10 50 100 200"}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$OUT"
export AWS_PAGER=""
# owner token per step: access tokens live 15 min and a full 8-step run takes ~17 min,
# so a single login expires mid-run (the 2026-09-19 write-200 row: 1306 x 401). One login
# per step is 8 logins in ~17 min, well under the 10/min limiter.
login() {
  curl -sS -X POST "$BASE/api/users/login" -H 'Content-Type: application/json' \
    -d '{"email":"admin@postershop.com","password":"admin1234"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'
}
# replica sampler
( while true; do
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    o=$(kubectl get deploy orders -n postershop -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "?")
    c=$(kubectl get deploy catalog -n postershop -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "?")
    i=$(kubectl get deploy inventory -n postershop -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "?")
    h=$(kubectl get hpa -n postershop --no-headers 2>/dev/null | awk '{printf "%s=%s/%s ", $1, $3, $7}')
    echo "$ts,$o,$c,$i,$h" >> "$OUT/replicas.csv"; sleep 10; done ) &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
for kind in ${KINDS:-read write}; do
  for v in $VUS; do
    echo "=== $(date -u +%H:%M:%S) $kind vus=$v $DUR" | tee -a "$OUT/steps.log"
    TOKEN=$(login); [ -n "$TOKEN" ] || { echo "no token"; exit 1; }
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$kind,$v,start" >> "$OUT/replicas.csv"
    k6 run --quiet -e BASE="$BASE" -e PATH_KIND="$kind" -e VUS="$v" -e DURATION="$DUR" -e TOKEN="$TOKEN" \
      --summary-export "$OUT/$kind-$v.json" "$HERE/step.js" 2>&1 | tail -n 25 | tee -a "$OUT/steps.log" || true
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ),$kind,$v,end" >> "$OUT/replicas.csv"
    sleep 20   # let the HPA settle a little between steps
  done
done
echo "done: $OUT"
