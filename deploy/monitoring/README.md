# PosterShop Monitoring

Prometheus + Grafana monitoring stack for the PosterShop platform.

> **See also**: [LOGGING.md](LOGGING.md) for centralized logging with Loki.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Grafana Dashboard                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ Overview │ │  Orders  │ │Inventory │ │   HPA    │        │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘        │
└───────┼────────────┼────────────┼────────────┼──────────────┘
        │            │            │            │
        └────────────┴────────────┴────────────┘
                           │
                    ┌──────┴──────┐
                    │  Prometheus │
                    └──────┬──────┘
                           │ scrape /metrics
        ┌──────────────────┼──────────────────┐
        │         │        │        │         │
   ┌────┴───┐ ┌───┴───┐ ┌──┴──┐ ┌──┴──┐ ┌───┴────┐
   │ Users  │ │Catalog│ │Order│ │ ... │ │Frontend│
   └────────┘ └───────┘ └─────┘ └─────┘ └────────┘
```

## Quick Start

### Option 1: Using kube-prometheus-stack (recommended)

```bash
# Add Prometheus Helm repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Install kube-prometheus-stack
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --values prometheus-values.yaml

# Apply ServiceMonitors for our apps
kubectl apply -f servicemonitors.yaml -n postershop

# Import Grafana dashboards
kubectl apply -f grafana-dashboards-configmap.yaml -n monitoring
```

### Option 2: Existing Prometheus

If you already have Prometheus installed:

```bash
# Apply ServiceMonitors
kubectl apply -f servicemonitors.yaml -n postershop

# Import dashboards manually via Grafana UI
# Use JSON files in this directory
```

## Files

| File | Description |
|------|-------------|
| `prometheus-values.yaml` | Helm values for kube-prometheus-stack |
| `servicemonitors.yaml` | ServiceMonitor CRDs to scrape our services |
| `alertrules.yaml` | PrometheusRule CRDs for alerting |
| `grafana-dashboard-overview.json` | Main platform overview dashboard |
| `grafana-dashboard-orders.json` | Orders service deep-dive |
| `grafana-dashboard-inventory.json` | Inventory service deep-dive |
| `grafana-dashboard-hpa.json` | HPA autoscaling dashboard |
| `grafana-dashboards-configmap.yaml` | ConfigMap for auto-loading dashboards |

## Available Metrics

### Common Metrics (all services)
- `http_requests_total{service, method, path, status}` - Request count
- `http_request_duration_seconds{service, path}` - Request latency histogram

### Orders Service
- `orders_created_total` - Total orders created
- `orders_by_status{status}` - Orders by status gauge
- `order_total_amount` - Order amount histogram
- `inventory_reservation_failures_total{reason}` - Failed reservations

### Inventory Service
- `inventory_stock_level{sku}` - Current stock per SKU
- `inventory_active_reservations` - Active reservation count
- `inventory_reservations_expired_total` - Expired reservations

### Production Service
- `production_jobs_total{status}` - Jobs by status
- `production_job_duration_seconds` - Job processing time

## Alerting

Pre-configured alerts:
- **HighErrorRate** - >5% error rate for 5 minutes
- **SlowRequests** - P95 latency >2s for 5 minutes
- **LowInventory** - Stock below threshold
- **OrderBacklog** - Too many pending orders
- **ServiceDown** - Service not responding

## Accessing Dashboards

### Port-forward Grafana
```bash
kubectl port-forward svc/prometheus-grafana 3000:80 -n monitoring
# Open http://localhost:3000
# Default credentials: admin / prom-operator
```

### Via Ingress
Configure ingress in `prometheus-values.yaml` for production access.

