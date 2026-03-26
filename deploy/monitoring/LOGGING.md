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
{job="postershop", container="orders"}

# Errors only
{job="postershop"} |= "ERROR"

# JSON filter: specific order
{job="postershop"} | json | order_id = 123

# Filter by correlation ID (trace a request)
{job="postershop"} | json | correlation_id = "abc123-def456"

# Count errors by service (last hour)
sum by (service) (count_over_time({job="postershop"} | json | level = "ERROR" [1h]))

# Latency issues (requests > 1s)
{job="postershop"} | json | duration_ms > 1000
```

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

# Query all logs for that request
{job="postershop"} | json | correlation_id = "my-trace-123"
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
