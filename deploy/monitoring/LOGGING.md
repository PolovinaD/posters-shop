# Centralized Logging with Loki

PosterShop uses **Grafana Loki** for log aggregation with **Fluent Bit** for log collection.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Grafana UI                            │
│              (Query logs via LogQL)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                        Loki                                 │
│          (Log storage & indexing)                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Fluent Bit                               │
│         (DaemonSet on each node)                            │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ orders   │  │production│  │inventory │  │   ...    │    │
│  │  logs    │  │  logs    │  │  logs    │  │          │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Log Format

All services output JSON-structured logs:

```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO",
  "service": "orders",
  "logger": "main",
  "correlation_id": "abc123-def456",
  "path": "/orders/123",
  "message": "Order created",
  "order_id": 123,
  "customer_email": "test@example.com"
}
```

### Fields

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 timestamp (UTC) |
| `level` | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `service` | Service name (orders, production, etc.) |
| `logger` | Python module name |
| `correlation_id` | Request tracing ID (propagates across services) |
| `path` | HTTP request path (if applicable) |
| `message` | Human-readable log message |
| `*` | Additional structured fields |

## Installation

### Prerequisites

- Kubernetes cluster (EKS)
- Helm v3
- Prometheus/Grafana stack (optional, for dashboards)

### 1. Add Helm Repositories

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
```

### 2. Install Loki

```bash
helm install loki grafana/loki \
  --namespace monitoring \
  --create-namespace \
  -f loki-values.yaml
```

### 3. Install Fluent Bit

```bash
helm install fluent-bit fluent/fluent-bit \
  --namespace monitoring \
  -f fluent-bit-values.yaml
```

### 4. Configure Grafana Data Source

If using kube-prometheus-stack, add Loki as a data source:

```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasource-loki
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  loki-datasource.yaml: |-
    apiVersion: 1
    datasources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki-gateway.monitoring.svc.cluster.local
      jsonData:
        maxLines: 1000
EOF
```

## Querying Logs

### LogQL Examples

```logql
# All logs from orders service
{job="postershop", service="orders"}

# Same thing via the container label (works only after the label fix below is applied)
{job="postershop", container="orders"}

# Errors only
{job="postershop"} |= "ERROR"

# JSON filter: specific order
{job="postershop"} | json | order_id = 123

# Trace a request across services.
# correlation_id is a PROMOTED STREAM LABEL, so it belongs inside the selector —
# this is an index lookup, not a scan of every line.
{job="postershop", correlation_id="abc123-def456"}

# Count errors by service (last hour)
sum by (service) (count_over_time({job="postershop"} | json | level = "ERROR" [1h]))

# Latency issues (requests > 1s)
{job="postershop"} | json | duration_ms > 1000
```

### Stream labels

A Loki stream here is keyed by:

| Label | Source |
|-------|--------|
| `job` | literal `postershop`, set in the Loki output |
| `namespace`, `pod`, `container` | the nested `kubernetes` map, via bracket-notation record accessors (`$kubernetes['pod_name']`) |
| `level`, `service`, `correlation_id` | root keys of the app's JSON line, lifted there by the `parser` filter |

Every one of those is a **record accessor**, and out_loki silently skips a label for
a record whose accessor does not resolve — debug level, no error, no crash. That is
how `namespace`, `pod` and `container` went missing for months while
`{job="postershop", service="orders"}` kept working: the `Rename kubernetes.pod_name pod`
rules that were supposed to create them never fired, because `filter_modify` compares
rule keys as literal top-level names and cannot address a nested map. Fixed by
addressing the map directly — see `fluent-bit-values.yaml`.

`correlation_id` being a label is what makes the trace query above an index lookup.
It is also what makes stream cardinality track request count — see below.

### Health-probe filtering

Fluent Bit drops health-probe log lines before they ever reach Loki. **Measured
2026-08-17: 102 of 200 lines from an orders pod (51%) were probe traffic**, because
`/readyz` (every 10s), `/healthz` (every 20s) and `/metrics` (every 15s) run forever
whether or not anyone is using the shop — 13 requests per minute per pod at zero load.
Each probe minted its own `correlation_id` and therefore its own Loki stream, which is
what drove `{job="postershop"}` to 2286 streams per 15 minutes and OOMKilled `loki-0`
twice.

Dropped: both shapes each probe produces — the app's structured JSON line (matched on
the root `path` key) and uvicorn's plain-text access line (matched on `message`).

**Not** dropped, by design:

- anything with no `path` key and no matching `message` — worker logs, startup logs,
  business events, tracebacks. Fluent Bit's legacy grep treats a missing key as
  "no match", which for an `Exclude` rule means the record is **kept**. A real log line
  cannot be swallowed by this filter.
- near-miss paths: `/healthz-report` and `/api/orders/healthz` are kept. Both patterns
  are anchored.
- the frontend nginx access lines — different shape, no `correlation_id`, and
  `nginx.conf` already sets `access_log off` on its `/health` location.

### Applying a config change to an existing install

Nothing in this repo picks these files up on its own. `full-deploy.sh` guards both
`helm install loki` and `helm install fluent-bit` behind `if ! helm status <release>`,
so on an existing cluster it re-reads **neither** values file, and
`make monitoring-install` never mentions either release. Changes to
`fluent-bit-values.yaml` or `loki-values.yaml` must be applied by hand:

```bash
# 0. What is actually installed — neither chart version is pinned in this repo,
#    so read them off the cluster before upgrading anything.
helm list -n monitoring -o json | jq -r '.[] | "\(.name)\t\(.chart)\t\(.app_version)"'

# 1. Fluent Bit: pin --version to the chart version step 0 printed. An unpinned
#    upgrade would also jump Fluent Bit majors (the chart is at 0.58.0/appVersion
#    5.1.0 upstream today, this install dates from April) on top of the config change.
helm repo add fluent https://fluent.github.io/helm-charts
helm repo update
helm upgrade fluent-bit fluent/fluent-bit \
  --namespace monitoring \
  --version <chart version from step 0> \
  -f deploy/monitoring/fluent-bit-values.yaml \
  --wait --timeout 5m

# 2. Dashboards (the ConfigMap is what Grafana's sidecar imports).
kubectl apply -f deploy/monitoring/grafana-dashboards-configmap.yaml -n monitoring

# 3. Fluent Bit must be RUNNING, not crashlooping. A bad filter stanza stops all
#    log shipping, which is far worse than the noise it was meant to remove.
kubectl rollout status ds/fluent-bit -n monitoring --timeout=2m
kubectl get pods -n monitoring -l app.kubernetes.io/name=fluent-bit
kubectl logs -n monitoring -l app.kubernetes.io/name=fluent-bit --tail=50 \
  | grep -Ei "error|could not compile|invalid record accessor" || echo "no errors"

# 4. Probe lines are gone AND real lines still arrive. Use a window that STARTS
#    AFTER the rollout finished — older probe lines stay in Loki for the 7-day
#    retention and will otherwise show up and look like a failure.
kubectl port-forward svc/loki-gateway 3100:80 -n monitoring &
#   4a. expect ZERO results:
logcli --addr=http://localhost:3100 query \
  '{job="postershop", service="orders"} |= "/healthz"' --limit=20 --since=5m
#   4b. generate one real request, then expect FRESH lines for it:
curl -s "$ALB/api/catalog/products" > /dev/null
logcli --addr=http://localhost:3100 query \
  '{job="postershop", service="catalog"}' --limit=20 --since=5m
#       (Grafana Explore with the same two queries works just as well.)

# 5. The labels now resolve — this is the {namespace="postershop"} -> 0 streams bug.
curl -s "http://localhost:3100/loki/api/v1/label/namespace/values" | jq .
curl -s -G "http://localhost:3100/loki/api/v1/series" \
  --data-urlencode 'match[]={namespace="postershop"}' | jq '.data | length'
#    expect "postershop" in the values and a non-zero series count.

# 6. The number that started all of this. Was 2286 over 15 min.
curl -s -G "http://localhost:3100/loki/api/v1/series" \
  --data-urlencode 'match[]={job="postershop"}' \
  --data-urlencode "start=$(date -u -v-15M +%s)000000000" \
  --data-urlencode "end=$(date -u +%s)000000000" | jq '.data | length'
#    expect a >90% drop (tens, not thousands) once probe traffic stops minting
#    a correlation_id per request. If it does, the 1Gi limit and the
#    max_chunks_per_query 20000 backstop in loki-values.yaml stop being
#    load-bearing and can be revisited — with a fresh measurement, not a guess.

# 7. Grafana: open "PosterShop Orders" -> the Logs (Loki) panel must show rows.
#    This one works from step 2 alone; it does not depend on step 1.
```

Step 1 is deliberately a hand-run `helm upgrade`. Making `full-deploy.sh` re-read these
values on every run (`install` -> `upgrade --install`) was considered and left out: it
would also start re-upgrading Loki and its PVC-backed StatefulSet on every bootstrap.

### Via Grafana

1. Open Grafana (port-forward: `kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoring`)
2. Go to Explore → Select "Loki" data source
3. Enter LogQL query

### Via CLI (logcli)

```bash
# Install logcli
brew install logcli

# Port-forward Loki
kubectl port-forward svc/loki-gateway 3100:80 -n monitoring &

# Query logs
logcli query '{job="postershop"}' --limit=100
```

## Correlation ID Tracing

Requests are traced across services using `X-Correlation-ID` header:

1. **Incoming request** - If header present, use it; otherwise generate UUID
2. **Logging** - All logs include `correlation_id` field
3. **Outgoing requests** - Pass header to downstream services
4. **Response** - Return correlation ID in `X-Correlation-ID` header

### Trace a Request

```bash
# Make a request with correlation ID
curl -H "X-Correlation-ID: my-trace-123" http://your-alb/api/orders/

# Query all logs for that request. correlation_id is a promoted stream label,
# so it goes inside the selector — an index lookup rather than a line scan.
{job="postershop", correlation_id="my-trace-123"}
```

## Retention & Storage

| Setting | Value |
|---------|-------|
| Retention | 7 days |
| Storage | 10GB PVC (gp2) |
| Ingestion rate | 10MB/s per tenant |

To adjust, modify `loki-values.yaml`:

```yaml
loki:
  limits_config:
    retention_period: 336h  # 14 days
```

## Troubleshooting

### Check Fluent Bit Status

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=fluent-bit
kubectl logs -n monitoring -l app.kubernetes.io/name=fluent-bit --tail=50
```

### Check Loki Status

```bash
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki
kubectl logs -n monitoring -l app.kubernetes.io/name=loki --tail=50
```

### Verify Log Flow

```bash
# Check Fluent Bit metrics
kubectl port-forward svc/fluent-bit 2020:2020 -n monitoring
curl http://localhost:2020/api/v1/metrics/prometheus | grep fluentbit_output
```

### Common Issues

| Issue | Solution |
|-------|----------|
| No logs in Loki | Check Fluent Bit is running, verify log path matches |
| JSON not parsed | Ensure services output valid JSON to stdout |
| Missing correlation ID | Check middleware is added to FastAPI app |

## Cost Estimation

| Component | Resource | Monthly Cost |
|-----------|----------|--------------|
| Loki | 1x pod (256Mi) | ~$5 |
| Loki PVC | 10GB gp2 | ~$1 |
| Fluent Bit | DaemonSet (~64Mi/node) | ~$2/node |

Total: ~$10-15/month for small cluster

## Disabling Logging

To disable centralized logging:

```bash
helm uninstall fluent-bit -n monitoring
helm uninstall loki -n monitoring
```

Services will continue logging to stdout (viewable via `kubectl logs`).
