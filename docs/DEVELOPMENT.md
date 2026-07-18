# Development Guide

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- PostgreSQL 15+ (local or Docker)
- kubectl (for Kubernetes deployment)
- AWS CLI (for EKS deployment)

---

## Quick Start (Local Development)

### 1. Database Setup

**Option A: Local PostgreSQL**
```bash
# Create database
createdb postershop

# Set environment variable
export DATABASE_URL="postgresql://localhost/postershop"
```

**Option B: Docker PostgreSQL**
```bash
docker run -d \
  --name postershop-db \
  -e POSTGRES_DB=postershop \
  -e POSTGRES_PASSWORD=devpassword \
  -p 5432:5432 \
  postgres:15

export DATABASE_URL="postgresql://postgres:devpassword@localhost:5432/postershop"
```

### 2. Run Services

**Backend Services (each in separate terminal):**

```bash
# Users Service
cd services/users
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8001

# Catalog Service
cd services/catalog
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8002

# Orders Service
cd services/orders
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8003

# Production Service
cd services/production
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8004

# Logistics Service
cd services/logistics
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8005

# Inventory Service
cd services/inventory
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8006

# Payments Service (no database)
cd services/payments
pip install -r requirements.txt
uvicorn main:app --reload --port 8007

# Infra Service (no database)
cd services/infra
pip install -r requirements.txt
uvicorn main:app --reload --port 8008

# Notifications Service (no database, no migrations)
cd services/notifications
pip install -r requirements.txt
uvicorn main:app --reload --port 8009
```

Port assignments follow `docker-compose.yaml`, which is authoritative. Note the ordering:
orders is **8003** and inventory is **8006**, not the other way around.

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Opens at http://localhost:5173
```

### 3. Seed Data

```bash
# Seed catalog (products, sizes, frames)
curl -X POST http://localhost:8002/seed

# Seed inventory (stock for products)
curl -X POST http://localhost:8003/seed
```

---

## Common Development Tasks

### Running Migrations

```bash
# Create new migration
cd services/<service>
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1

# View migration history
alembic history
```

### Running Tests

```bash
# Run tests for a service (if tests exist)
cd services/<service>
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

### Viewing Logs

**Local (terminal output):**
Services log JSON to stdout. Use `jq` for pretty printing:
```bash
uvicorn main:app 2>&1 | jq
```

**Kubernetes:**
```bash
# View logs for a pod
kubectl logs -f deployment/orders -n postershop

# View logs with Loki (if configured)
# Use Grafana or LogCLI
```

### API Documentation

Each service has auto-generated OpenAPI docs:
- Users: http://localhost:8001/docs
- Catalog: http://localhost:8002/docs
- Orders: http://localhost:8003/docs
- Production: http://localhost:8004/docs
- Logistics: http://localhost:8005/docs
- Inventory: http://localhost:8006/docs
- Payments: http://localhost:8007/docs
- Infra: http://localhost:8008/docs
- Notifications: http://localhost:8009/docs

---

## Environment Variables

Create a `.env` file in each service directory:

```bash
# Common
DATABASE_URL=postgresql://localhost/postershop
LOG_LEVEL=INFO
ROOT_PATH=

# Service-specific (see ENV_VARS.md for full list)
JWT_SECRET=your-secret-key
INVENTORY_SERVICE_URL=http://localhost:8006
PRODUCTION_SERVICE_URL=http://localhost:8004
NOTIFICATIONS_SERVICE_URL=http://localhost:8009
```

> Host ports follow `docker-compose.yaml`, which is authoritative:
> users 8001, catalog 8002, orders 8003, production 8004, logistics 8005,
> inventory 8006, payments 8007, infra 8008, notifications 8009.
> Inside Docker Compose every service listens on container port 8000, so
> service-to-service URLs there use `http://<service>:8000` instead.

---

## Docker Build

```bash
# Build single service
docker build -t shop-platform/orders:latest services/orders

# Build for specific architecture (for M1/M2 Macs deploying to Linux)
docker build --platform linux/amd64 -t shop-platform/orders:latest services/orders
```

---

## Kubernetes Deployment

### Local (Minikube/Kind)

```bash
# Start cluster
minikube start

# Deploy all services
helm upgrade --install users deploy/charts/users -n postershop --create-namespace
helm upgrade --install catalog deploy/charts/catalog -n postershop
# ... repeat for other services
```

### AWS EKS

See [deploy/README.md](../deploy/README.md) for full EKS setup instructions.

```bash
# Quick deploy
./deploy/scripts/deploy.sh <service-name>

# Or use GitHub Actions workflow
```

---

## Useful Commands

### Database

```bash
# Connect to PostgreSQL
psql $DATABASE_URL

# List schemas
\dn

# List tables in schema
\dt orders_schema.*

# Check outbox events
SELECT id, event_type, delivered_at, retry_count FROM orders_schema.outbox_events;
```

### Kubernetes

```bash
# Get all resources in namespace
kubectl get all -n postershop

# Describe deployment
kubectl describe deployment orders -n postershop

# Port forward for local access
kubectl port-forward svc/orders 8000:8000 -n postershop

# View HPA status
kubectl get hpa -n postershop

# Scale deployment
kubectl scale deployment production --replicas=3 -n postershop
```

### Docker

```bash
# View running containers
docker ps

# View logs
docker logs <container-id> -f

# Clean up
docker system prune -a
```

---

## Debugging Tips

### Service won't start

1. Check DATABASE_URL is set correctly
2. Run migrations: `alembic upgrade head`
3. Check port isn't already in use
4. Look for import errors in logs

### Orders failing with "insufficient stock"

1. Check inventory was seeded: `curl http://localhost:8006/stock`
2. Verify SKUs match between catalog and inventory
3. Check for expired reservations

### Events not being delivered

1. Check outbox stats: `curl http://localhost:8003/orders/outbox/stats`
2. Verify `PRODUCTION_SERVICE_URL` and `NOTIFICATIONS_SERVICE_URL` are correct
3. Check that both subscriber services are running and healthy
4. Look for errors in outbox `last_error` field

Remember that `ORDER_PAID` and `ORDER_CANCELLED` fan out to **both** production and
notifications. If either subscriber is down, the whole event is retried and re-delivered
to the one that already succeeded — so a stuck event does not necessarily implicate the
service you first suspect.

### Emails not being sent

1. Confirm notifications is up: `curl http://localhost:8009/healthz`
2. Check the failure counter: `curl http://localhost:8009/metrics | grep notifications_email_send_failures_total`
3. With the default `EMAIL_PROVIDER=logging`, a successful send appears in the log as
   `Email (logging provider)` — no AWS involvement at all
4. A `{"status": "skipped", "reason": "no_customer_email"}` response means the event
   payload carried no address; check the emitting code path in orders
5. With `EMAIL_PROVIDER=ses`, a `503` means the provider raised — verify the IRSA role
   and that `EMAIL_FROM` is a verified identity in `SES_REGION`

### Frontend can't reach backend

1. Check CORS settings in backend
2. Verify API_BASE_URL in frontend config
3. Check network tab for actual error responses

---

## Adding a New Service

1. **Create service directory:**
   ```bash
   mkdir -p services/newservice
   ```

2. **Copy boilerplate from existing service:**
   ```bash
   cp services/catalog/{main.py,database.py,requirements.txt,Dockerfile} services/newservice/
   ```

3. **Set up Alembic — database-backed services only:**
   ```bash
   cd services/newservice
   alembic init alembic
   # Configure alembic.ini and env.py (see existing services)
   ```

   **Stateless services skip this step entirely.** `payments`, `infra` and
   `notifications` own no schema, have no `alembic/` directory, and no `models.py` or
   `database.py`. Do not add a schema to a service that does not need one.

4. **Create Helm chart:**
   ```bash
   cp -r deploy/charts/catalog deploy/charts/newservice
   # Update values.yaml with service name
   ```

   **For a stateless service, delete `templates/migration-job.yaml` from the copied
   chart.** Leaving it in place produces a Helm hook that runs `alembic upgrade head`
   against a service with no migrations, which fails the install. Compare against
   `deploy/charts/notifications/`, whose `templates/` holds only `deployment.yaml`.

5. **Add a ServiceMonitor:**
   Add an entry to `deploy/monitoring/servicemonitors.yaml` so Prometheus scrapes the
   new service's `/metrics`.

   **The `endpoints[].port` value must be the port NAME declared on the service's
   Kubernetes Service, not a port number and not an assumption.** Most services name it
   `http`, but `infra` names its port `http-metrics`. A ServiceMonitor whose port name
   matches nothing still appears healthy in `kubectl get servicemonitor` while scraping
   nothing at all — a silent failure that is harder to spot than a missing monitor.
   Check the chart's Service definition before writing the block.

6. **Add to deploy workflow:**
   Edit `.github/workflows/deploy.yaml` to include new service.
   Also add the service to the `SERVICES` list in `deploy/full-deploy.sh` and to the
   ECR repository creation loop in `deploy/README.md` — a service missing from either
   deploys into an `ImagePullBackOff`.

7. **Update documentation:**
   - Add to README.md service list **and its Service Documentation link list**
   - Create `services/newservice/README.md` (every service has one)
   - Add to ARCHITECTURE.md diagrams
   - Add to ENV_VARS.md, QUICK_REFERENCE.md port table, and docs/EVENT_CATALOG.md if it
     produces or consumes events
