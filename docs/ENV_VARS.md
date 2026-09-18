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
| `DESIGNS_SERVICE_URL` | Designs service base URL — the third `ORDER_PAID` subscriber (`/events/order-paid`, `outbox.py`) | `http://designs:8000` | No |
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

## Designs Service

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string (`designs_svc`, `search_path=designs_schema`; the service raises at import when unset) | - | Yes |
| `JWT_SECRET` | Verifies customer bearers and signs/verifies service-to-service tokens (`service_auth.py`) | - | Yes |
| `IMAGE_PROVIDER` | Image generation backend: `fake` (Pillow placeholder, no key), `openai`, `replicate`. A real provider without its key falls back to `fake` with a warning | `fake` | No |
| `OPENAI_API_KEY` | OpenAI key for the Images API (posters) and Chat Completions (style summary) | - | Yes (when `IMAGE_PROVIDER=openai`) |
| `OPENAI_IMAGE_MODEL` | Images API model | `gpt-image-1.5` | No |
| `OPENAI_IMAGE_QUALITY` | Images API quality (`low` / `medium` / `high`) | `medium` | No |
| `OPENAI_CHAT_MODEL` | Chat model that writes the style-profile summary | `gpt-4o-mini` | No |
| `OPENAI_BASE_URL` | OpenAI API base URL | `https://api.openai.com/v1` | No |
| `REPLICATE_API_TOKEN` | Replicate token (provider is unit-tested only — no token in this project) | - | Yes (when `IMAGE_PROVIDER=replicate`) |
| `REPLICATE_MODEL` | Replicate model, called at `/models/{model}/predictions` | `black-forest-labs/flux-schnell` | No |
| `REPLICATE_BASE_URL` | Replicate API base URL | `https://api.replicate.com/v1` | No |
| `STORAGE_BACKEND` | Where PNGs live: `local` (directory / volume) or `s3` | `local` | No |
| `DESIGNS_STORAGE_DIR` | Directory for `local` storage (compose: the `designs-data` volume; chart: an `emptyDir`) | `/data/images` | No |
| `DESIGNS_S3_BUCKET` | Bucket for `s3` storage | - | Yes (when `STORAGE_BACKEND=s3`) |
| `DESIGNS_S3_REGION` | Bucket region; falls back to `AWS_REGION` | `eu-north-1` | No |
| `DESIGNS_PUBLIC_URL_PREFIX` | Prefix of the `image_url` handed to the shop (`/api/designs/images/{key}` through the nginx / ALB proxy) | `/api/designs/images` | No |
| `CATALOG_SERVICE_URL` | Catalog base URL for `POST /internal/products` (print-this) | `http://catalog:8000` | No |
| `INVENTORY_SERVICE_URL` | Inventory base URL for `POST /internal/stock` (virtual stock) | `http://inventory:8000` | No |
| `AI_DAILY_QUOTA` | Generations per customer per UTC day (failed rows do not count); `0` = unlimited; the owner role is exempt | `10` | No |
| `AI_POSTER_BASE_PRICE` | A3 price of a printed design; A4 / A2 / A1 are −5 / +10 / +25 (the catalog seed ladder) | `29.99` | No |
| `AI_POSTER_STOCK` | Virtual stock units created per variant at print time | `1000` | No |
| `DESIGNS_WORKER_POLL_INTERVAL` | Seconds the worker sleeps when no row is due | `1.0` | No |
| `DESIGNS_MAX_ATTEMPTS` | Provider attempts before a generation is `failed` (backoff 5 s / 30 s / 120 s) | `3` | No |
| `CB_FAILURE_THRESHOLD` | Consecutive failures that open the provider / catalog / inventory circuit breakers | `5` | No |
| `CB_RECOVERY_TIMEOUT` | Seconds a breaker stays open before a trial call | `30` | No |

**Note:** Designs is DB-backed (`designs_schema`: `generations`, `saved_prompts`, `style_profiles`,
`purchases`, `processed_events`) — set `DATABASE_URL` and run its Alembic migration like the
other DB services (`designs-migrate` in compose, the chart's migration Job in Kubernetes).

**No secret is required for S3.** Like SES, the bucket credentials come from IRSA: the chart's
`serviceAccount.name` points at an eksctl-created, role-annotated ServiceAccount
(`deploy/designs-setup.sh`), so there is no access key to store. See
[deploy/README.md](../deploy/README.md) under "Design Image Storage (S3 via IRSA)".

**`IMAGE_PROVIDER` and `STORAGE_BACKEND` are not in the chart's `env` list.** They (and the
model names, bucket and region) are rendered from the `provider:` and `storage:` scalar blocks in
`deploy/charts/designs/values.yaml`, so `--set provider.image=openai` and
`--set storage.backend=s3 --set storage.bucket=…` are index-safe; `deploy/lib/live-config.sh`
reads them back from the running Deployment so a CI deploy never resets them.

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
- `db-credentials` - DATABASE_URL for all database-backed services (in the charts this is
  `postershop-db`, an ExternalSecret from Secrets Manager `postershop/database` whose keys are
  `DATABASE_URL_USERS` … `DATABASE_URL_NOTIFICATIONS`, `DATABASE_URL_DESIGNS`)
- `jwt-secret` - JWT_SECRET for users service
- `stripe-secrets` - STRIPE_WEBHOOK_SECRET for orders/payments
- `postershop-escrow` - `OWNER_PRIVATE_KEY` for payments (`ESCROW_OWNER_PRIVATE_KEY`), an
  ExternalSecret from Secrets Manager `postershop/escrow`
  (`deploy/secrets/external-secrets.yaml`). `deploy/full-deploy.sh` generates the key once
  and reuses it on every later run — rotating it would orphan every open contract
- `postershop-designs` - `OPENAI_API_KEY` and `REPLICATE_API_TOKEN` for designs, an
  ExternalSecret from Secrets Manager `postershop/designs`. Both `secretKeyRef`s in the chart are
  `optional: true`, so an install without the Secret still schedules and runs the fake provider.
  `deploy/full-deploy.sh` writes the self-describing placeholder
  `MISSING-set-postershop/designs` for whichever key is not configured (ESO is all-or-nothing on
  the properties it maps), and never overwrites a real value already in AWS

**Notifications requires no secret.** Its only external credential is AWS SES access,
which is granted through an IAM role assumed via IRSA rather than a stored key. Nothing
about SES authentication belongs in a Kubernetes Secret or in AWS Secrets Manager. The same
holds for designs' S3 access — only the provider keys above are secrets.

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

The designs chart additionally exposes scalars that the Deployment template renders into
env vars (index-safe for `--set`, unlike the `env` list):

```yaml
provider:
  image: "fake"                        # IMAGE_PROVIDER: fake | openai | replicate
  openaiImageModel: "gpt-image-1.5"
  openaiImageQuality: "medium"
  openaiChatModel: "gpt-4o-mini"
  replicateModel: "black-forest-labs/flux-schnell"
storage:
  backend: "local"                     # STORAGE_BACKEND: local (emptyDir) | s3
  dir: "/data/images"
  bucket: ""                           # DESIGNS_S3_BUCKET when set
  region: ""                           # DESIGNS_S3_REGION when set
serviceAccount:
  name: ""                             # e.g. designs — the IRSA ServiceAccount for s3
```

No secret is required for S3 — credentials come from IRSA (`deploy/designs-setup.sh`).

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
