# Environment Variables

This document lists all environment variables used by each service.

---

## Common Variables (All Services)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes (except payments, infra, notifications) |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` | No |
| `SERVICE_NAME` | Service identifier for logging | Service-specific | No |
| `ROOT_PATH` | API path prefix (for ALB routing) | `""` | No |

---

## Users Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `JWT_SECRET` | Secret key for JWT signing | `change_me` | Yes (in prod) |
| `JWT_EXPIRE_MINUTES` | Token expiration time | `60` | No |

---

## Catalog Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `INVENTORY_SERVICE_URL` | Inventory service base URL | `http://inventory:8000` | No |

---

## Inventory Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |

---

## Orders Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `INVENTORY_SERVICE_URL` | Inventory service base URL | `http://inventory:8000` | No |
| `PRODUCTION_SERVICE_URL` | Production service base URL | `http://production:8000` | No |
| `PAYMENT_SERVICE_URL` | Payment service base URL | `http://payments:8000` | No |
| `NOTIFICATIONS_SERVICE_URL` | Notifications service base URL (outbox email fan-out) | `http://notifications:8000` | No |
| `STRIPE_WEBHOOK_SECRET` | Webhook signature verification | `whsec_test_secret_key_12345` | Yes (in prod) |

---

## Production Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `ORDERS_SERVICE_URL` | Orders service base URL | `http://orders:8000` | No |
| `LOGISTICS_SERVICE_URL` | Logistics service base URL | `http://logistics:8000` | No |

---

## Logistics Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `ORDERS_SERVICE_URL` | Orders service base URL | `http://orders:8000` | No |
| `JWT_SECRET` | JWT secret (for courier auth) | `change_me` | No |

---

## Payments Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `STRIPE_WEBHOOK_SECRET` | Webhook signing secret | `whsec_test_secret_key_12345` | No |
| `ORDERS_WEBHOOK_URL` | Orders webhook endpoint | `http://orders:8000/webhooks/stripe` | No |

**Note:** Payments service is stateless (no database) - uses in-memory storage for sessions.

---

## Infra Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `NAMESPACE` | Kubernetes namespace to manage | `postershop` | No |

**Note:** Infra service automatically detects if running in Kubernetes cluster.

---

## Notifications Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `EMAIL_PROVIDER` | Transport selector: `ses` for AWS SES, anything else for the logging provider | `logging` | No |
| `EMAIL_FROM` | Sender address — must be a verified SES identity when using SES | `no-reply@postershop.example` | Yes (when `EMAIL_PROVIDER=ses`) |
| `SES_REGION` | Region holding the verified SES sender identity | `eu-central-1` | No |

**Note:** Notifications service is stateless (no database, no Alembic migrations).

**On `SES_REGION` vs `AWS_REGION`:** these are deliberately independent. `AWS_REGION`
(`eu-north-1`) is where the EKS cluster runs; `SES_REGION` is where the sender identity
was verified. SES is a regional service, and a verified identity does not have to live in
the region of the workload calling it. Set `SES_REGION=eu-north-1` if you verify your
identity there — the difference is a configuration choice, not a misconfiguration.

**No secret is required for SES.** Credentials come from IRSA (*IAM Roles for Service
Accounts*), so there is no access key to store. See
[deploy/README.md](../deploy/README.md) under "Email Delivery Setup (SES via IRSA)".

---

## Frontend

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `VITE_API_BASE_URL` | Backend API base URL | `/` | No |

**Note:** Frontend uses Vite; environment variables must be prefixed with `VITE_`.

---

## Kubernetes Secrets

In Kubernetes, sensitive variables are stored in Secrets:

```yaml
# Example: db-credentials secret
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: postershop
type: Opaque
stringData:
  DATABASE_URL: "postgresql://user:pass@host:5432/db"
```

**Required Secrets:**
- `db-credentials` - DATABASE_URL for all database-backed services
- `jwt-secret` - JWT_SECRET for users service
- `stripe-secrets` - STRIPE_WEBHOOK_SECRET for orders/payments

**Notifications requires no secret.** Its only external credential is AWS SES access,
which is granted through an IAM role assumed via IRSA rather than a stored key. Nothing
about SES authentication belongs in a Kubernetes Secret or in AWS Secrets Manager.

---

## Helm Chart Configuration

Environment variables are configured in each service's `values.yaml`:

```yaml
env:
  SERVICE_NAME: orders
  LOG_LEVEL: INFO
  INVENTORY_SERVICE_URL: http://inventory:8000
  PRODUCTION_SERVICE_URL: http://production:8000

secrets:
  - name: DATABASE_URL
    secretName: db-credentials
    secretKey: DATABASE_URL
```

---

## Local Development (.env file)

Create `.env` in each service directory:

```bash
# services/orders/.env
DATABASE_URL=postgresql://localhost/postershop
LOG_LEVEL=DEBUG
INVENTORY_SERVICE_URL=http://localhost:8003
PRODUCTION_SERVICE_URL=http://localhost:8005
PAYMENT_SERVICE_URL=http://localhost:8007
STRIPE_WEBHOOK_SECRET=whsec_test_secret_key_12345
```

Load with:
```bash
export $(cat .env | xargs)
```

Or use python-dotenv (already in requirements).
