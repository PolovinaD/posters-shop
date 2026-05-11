# Quick Reference

Practical reference card for the PosterShop platform. For deeper docs, see [README.md](../README.md#documentation).

## Service Ports (Local Docker Compose)

| Service    | Host Port | Container Port |
|------------|-----------|----------------|
| users      | 8001      | 8000           |
| catalog    | 8002      | 8000           |
| orders     | 8003      | 8000           |
| production | 8004      | 8000           |
| logistics  | 8005      | 8000           |
| inventory  | 8006      | 8000           |
| payments   | 8007      | 8000           |
| infra      | 8008      | 8000           |
| frontend   | 3000      | 80             |
| postgres   | 5432      | 5432           |

## Common Environment Variables

| Variable | Example | Used by |
|----------|---------|---------|
| `AWS_REGION` | `eu-north-1` | Makefile, deploy scripts |
| `AWS_ACCOUNT_ID` | `123456789012` | Makefile, deploy scripts |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `postgres` / `postgres` / `posters_shop` | Local postgres container |
| `<SERVICE>_DATABASE_URL` | `postgresql://users_svc:users_pass@db:5432/posters_shop` | Each DB-backed service |
| `JWT_SECRET` | `your-super-secret-jwt-key` | users, catalog, orders, logistics, inventory, infra |
| `CORS_ORIGINS` | `http://localhost:3000` | All services |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | `sk_test_...` / `whsec_...` | orders, payments |
| `CB_FAILURE_THRESHOLD` / `CB_RECOVERY_TIMEOUT` | `5` / `30` | orders (circuit breaker) |
| `<SERVICE>_SERVICE_URL` | `http://inventory:8000` | Inter-service HTTP clients |

Full list: see [env.example](../env.example).

## Local Dev Commands

```bash
# Bring everything up (migrations run automatically via *-migrate services)
docker compose up -d

# Tail logs across all services
docker compose logs -f

# Tail one service
docker compose logs -f orders

# Tear everything down
docker compose down

# Recreate volumes (wipes DB)
docker compose down -v

# Run alembic migrations manually for a service
docker compose run --rm users-migrate

# Seed catalog and inventory
curl -X POST http://localhost:8002/seed
curl -X POST http://localhost:8006/seed
```

## Common curl Examples

```bash
# Health check
curl localhost:8001/healthz

# Prometheus metrics
curl localhost:8003/metrics

# Login -> JWT token
curl -X POST localhost:8001/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@postershop.com","password":"admin1234"}'

# Seed catalog (admin token required if auth enforced)
curl -X POST localhost:8002/seed

# Seed inventory
curl -X POST localhost:8006/seed

# List orders (with auth)
curl localhost:8003/orders \
  -H "Authorization: Bearer $TOKEN"
```

## Default Credentials

| Role  | Email                  | Password    | Source                       |
|-------|------------------------|-------------|------------------------------|
| Admin | `admin@postershop.com` | `admin1234` | `services/users/init_db.py`  |

These are seeded on first migration run. Change in production.
