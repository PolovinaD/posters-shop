# Infrastructure Service

Kubernetes cluster management and monitoring API.

## Purpose

- List and manage deployments
- View pod status and logs
- Control HPA (Horizontal Pod Autoscaler)
- Provide cluster overview for admin UI

## Tech Stack

- FastAPI
- kubernetes Python client (in-cluster only)
- WebSocket (live logs)
- Mock data for local development

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /healthz | Health check | - |
| GET | /deployments | List deployments | Admin |
| GET | /deployments/{name} | Get deployment | Admin |
| POST | /deployments/{name}/scale | Scale deployment | Admin |
| POST | /deployments/{name}/restart | Restart deployment | Admin |
| GET | /pods | List pods | Admin |
| DELETE | /pods/{name} | Delete pod | Admin |
| GET | /pods/{name}/logs | Get pod logs | Admin |
| GET | /hpa | List HPAs | Admin |
| PATCH | /hpa/{name} | Update HPA | Admin |
| GET | /cluster | Cluster overview | Admin |
| WS | /ws/logs/{pod} | Live log stream | Admin |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| NAMESPACE | K8s namespace to manage | `postershop` |

## Local Development

```bash
cd services/infra
pip install -r requirements.txt
uvicorn main:app --reload --port 8008
```

**Note:** Returns mock data when not running in Kubernetes cluster.

## Cluster Detection

Automatically detects if running in Kubernetes:
```python
IN_CLUSTER = os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount/token')
```

## Mock Data (Local)

When not in cluster, returns simulated data for:
- 8 deployments (users, catalog, orders, etc.)
- CPU/memory usage
- HPA configuration

## Kubernetes Permissions

Requires RBAC permissions in cluster:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: infra-service
rules:
  - apiGroups: ["apps"]
    resources: ["deployments", "deployments/scale"]
    verbs: ["get", "list", "patch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "delete"]
  - apiGroups: ["autoscaling"]
    resources: ["horizontalpodautoscalers"]
    verbs: ["get", "list", "patch"]
  - apiGroups: ["metrics.k8s.io"]
    resources: ["pods", "nodes"]
    verbs: ["get", "list"]
```

## Deployment Info Response

```json
{
  "name": "orders",
  "replicas": 2,
  "available": 2,
  "ready": 2,
  "cpu_usage": 150.5,
  "memory_usage": 256.0,
  "status": "healthy",
  "image": "123456.dkr.ecr.us-east-1.amazonaws.com/orders:latest",
  "created_at": "2024-01-15T10:00:00Z"
}
```

## Status Calculation

| Condition | Status |
|-----------|--------|
| available == replicas | healthy |
| available > 0 | degraded |
| available == 0 | unhealthy |

## WebSocket Logs

Connect to `/ws/logs/{pod_name}` for streaming logs:
- Polls every 1 second
- Returns last 10 lines since last check
- Mock data in local mode

## Dependencies

- **Kubernetes API**: When running in cluster
- None: When running locally (mock mode)
