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

# Inventory Service
cd services/inventory
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8003

# Orders Service
cd services/orders
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8004

# Production Service
cd services/production
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8005

# Logistics Service
cd services/logistics
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
```

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
- Inventory: http://localhost:8003/docs
- Orders: http://localhost:8004/docs
- Production: http://localhost:8005/docs
- Logistics: http://localhost:8006/docs
- Payments: http://localhost:8007/docs
- Infra: http://localhost:8008/docs

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
INVENTORY_SERVICE_URL=http://localhost:8003
PRODUCTION_SERVICE_URL=http://localhost:8005
```

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

1. Check inventory was seeded: `curl http://localhost:8003/stock`
2. Verify SKUs match between catalog and inventory
3. Check for expired reservations

### Events not being delivered

1. Check outbox stats: `curl http://localhost:8004/outbox/stats`
2. Verify PRODUCTION_SERVICE_URL is correct
3. Check production service is running and healthy
4. Look for errors in outbox `last_error` field

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

3. **Set up Alembic:**
   ```bash
   cd services/newservice
   alembic init alembic
   # Configure alembic.ini and env.py (see existing services)
   ```

4. **Create Helm chart:**
   ```bash
   cp -r deploy/charts/catalog deploy/charts/newservice
   # Update values.yaml with service name
   ```

5. **Add to deploy workflow:**
   Edit `.github/workflows/deploy.yaml` to include new service

6. **Update documentation:**
   - Add to README.md service list
   - Add to ARCHITECTURE.md diagrams
   - Add to ENV_VARS.md
