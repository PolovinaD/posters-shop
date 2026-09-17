# Environment Variables

This document lists all environment variables used by each service.

---

## Common Variables (All Services)

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes (except payments, infra) |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` | No |
| `SERVICE_NAME` | Service identifier for logging | Service-specific | No |
| `ROOT_PATH` | API path prefix (for ALB routing) | `""` | No |
| `CORS_ORIGINS` | Comma-separated list of allowed browser origins | `http://localhost:3000` | No |

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
| `STRIPE_SECRET_KEY` | Stripe API key used to create and read checkout sessions | - | Yes (in prod) |
| `STRIPE_WEBHOOK_SECRET` | Webhook signature verification | `whsec_test_secret_key_12345` | Yes (in prod) |
| `CB_FAILURE_THRESHOLD` | Consecutive failures that open the inventory/payment circuit breaker | `5` | No |
| `CB_RECOVERY_TIMEOUT` | Seconds the circuit stays open before a trial call | `30` | No |
| `ESCROW_RECONCILE_INTERVAL` | Seconds between passes of the escrow reconciler worker (one worker per replica; `escrow_reconciler.py`) | `15` | No |

**`CB_FAILURE_THRESHOLD` counts per process, not per platform.** Each orders replica keeps
its own failure counter, so the effective platform-wide threshold is 5 x the current
replica count (see `docs/KNOWN_LIMITATIONS.md` #9).

---

## Production Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `ORDERS_SERVICE_URL` | Orders service base URL | `http://orders:8000` | No |
| `LOGISTICS_SERVICE_URL` | Logistics service base URL | `http://logistics:8000` | No |
| `JWT_SECRET` | Signs and verifies service-to-service tokens (`service_auth.py`) | `change_me` | Yes |

---

## Logistics Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | Yes |
| `ORDERS_SERVICE_URL` | Orders service base URL | `http://orders:8000` | No |
| `JWT_SECRET` | JWT secret (for courier auth) | `change_me` | No |
| `LOGISTICS_AUTO_ADVANCE_INTERVAL` | Seconds a shipment sits in a status before the worker advances it | `120` | No |
| `LOGISTICS_DEFAULT_COURIER_WALLET` | Courier wallet sent to orders on pick-up when the status update carries none; unset = the auto-advance worker binds no wallet. docker-compose and the chart set Ganache account[2] | `-` | No |

---

## Payments Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `STRIPE_SECRET_KEY` | Stripe API key used to create checkout sessions | - | Yes (in prod) |
| `STRIPE_WEBHOOK_SECRET` | Webhook signing secret | `whsec_test_secret_key_12345` | No |
| `FRONTEND_URL` | Base URL a customer returns to after Stripe checkout | `http://localhost:3000` | No |
| `JWT_SECRET` | Signs and verifies service-to-service tokens (`service_auth.py`) | `change_me` | Yes |
| `ESCROW_RPC_URL` | Ethereum JSON-RPC endpoint payments talks to (web3) | `http://ganache:8545` | No |
| `ESCROW_PUBLIC_RPC_URL` | The RPC URL handed to the browser in `/v1/escrow/config` (the nginx `/rpc` proxy) | `/rpc` | No |
| `ESCROW_OWNER_PRIVATE_KEY` | Shop-owned key that deploys every `OrderEscrow` contract and sends everything but `pay()`; without it payments starts with escrow disabled | `-` | Yes (to enable escrow) |
| `WEI_PER_USD` | Fixed conversion rate, wei per dollar (0.001 ETH) — no oracle | `1000000000000000` | No |
| `ESCROW_COURIER_SHARE_BPS` | Courier's share of the price on `confirmDelivery()`, in basis points (20 %) | `2000` | No |
| `ESCROW_OWNER_MIN_BALANCE_ETH` | On Ganache: top the owner up from the node's account[0] when its balance is below this | `10` | No |
| `ESCROW_OWNER_TOPUP_ETH` | How much that startup top-up transfers | `100` | No |
| `ESCROW_EXPOSE_DEMO_ACCOUNTS` | Serve Ganache's ten deterministic accounts (with keys) at `/v1/escrow/demo-accounts`; only honoured when the node is Ganache | `true` | No |
| `ESCROW_RPC_TIMEOUT` | Seconds per JSON-RPC call | `5` | No |

**Note:** Payments is stateless: checkout sessions live at Stripe and escrow state lives on
chain and on the orders row. Defaults above are the `os.getenv` values in
`services/payments/escrow.py`.

---

## Infra Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `NAMESPACE` | Kubernetes namespace to manage | `postershop` | No |
| `LOKI_URL` | Loki gateway base URL for the log-query proxy | `http://loki-gateway.monitoring.svc.cluster.local` | No |
| `LOKI_SERVICE_LABEL` | Loki stream label carrying the service name | `service` | No |

**Note:** Infra service automatically detects if running in Kubernetes cluster.

---

## Notifications Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string (the service raises at import when unset) | - | Yes |
| `EMAIL_PROVIDER` | Transport selector: `ses` for AWS SES, anything else for the logging provider | `logging` | No |
| `EMAIL_FROM` | Sender address — must be a verified SES identity when using SES | `no-reply@postershop.example` | Yes (when `EMAIL_PROVIDER=ses`) |
| `SES_REGION` | Region holding the verified SES sender identity | `eu-central-1` | No |
| `JWT_SECRET` | Signs and verifies service-to-service tokens (`service_auth.py`) | `change_me` | Yes |

**Note:** Notifications service is now DB-backed (`notifications_schema`, one `processed_events` table for durable idempotency) — set `DATABASE_URL` and run its Alembic migration like the other DB services (quick-260815-m0m).

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
- `postershop-escrow` - `OWNER_PRIVATE_KEY` for payments (`ESCROW_OWNER_PRIVATE_KEY`), an
  ExternalSecret from Secrets Manager `postershop/escrow`
  (`deploy/secrets/external-secrets.yaml`). `deploy/full-deploy.sh` generates the key once
  and reuses it on every later run — rotating it would orphan every open contract

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
