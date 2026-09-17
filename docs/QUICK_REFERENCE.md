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
| notifications | 8009   | 8000           |
| frontend   | 3000      | 80             |
| postgres   | 5432      | 5432           |
| ganache    | 8545      | 8545           |

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
| `NOTIFICATIONS_SERVICE_URL` | `http://notifications:8000` | orders (outbox email fan-out) |
| `EMAIL_PROVIDER` | `logging` / `ses` | notifications (transport selector) |
| `EMAIL_FROM` | `no-reply@postershop.example` | notifications (SES verified sender) |
| `SES_REGION` | `eu-central-1` | notifications (independent of `AWS_REGION` by design) |
| `ESCROW_OWNER_PRIVATE_KEY` | `0x...` (64 hex) | payments (escrow disabled without it; compose ships a dev key) |
| `WEI_PER_USD` / `ESCROW_COURIER_SHARE_BPS` | `1000000000000000` / `2000` | payments (fixed rate 0.001 ETH per dollar; courier share 20 %) |
| `ESCROW_RECONCILE_INTERVAL` | `15` | orders (escrow reconciler worker, seconds) |
| `LOGISTICS_DEFAULT_COURIER_WALLET` | `0x22d491bde2303f2f43325b2108d26f1eaba1e32b` (Ganache account[2]) | logistics (wallet the auto-advance worker binds on pick-up) |

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

# Or do all of it as the owner, and set the demo courier's wallet to Ganache account 3
make dev-seed

# Recompile the OrderEscrow contract into the committed artifact (solc 0.8.28 in docker)
make contract-compile

# Escrow config as the SPA sees it — "enabled": false means no owner key or Ganache is down
curl localhost:8007/v1/escrow/config

# Is the Ethereum simulator up? (-> {"jsonrpc":"2.0","id":1,"result":"0x539"} = chainId 1337)
curl -s localhost:8545 -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'
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

# Notifications smoke test — the default logging provider needs no AWS credentials,
# so this works out of the box. The rendered email lands in the service log.
curl -X POST localhost:8009/events/order-paid \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": 1,
    "event_type": "ORDER_PAID",
    "aggregate_type": "order",
    "aggregate_id": "123",
    "payload": {
      "order_id": 123,
      "customer_email": "customer@example.com",
      "total_amount": "99.99"
    }
  }'
# -> {"status":"sent","event_id":1}
# Repeat the same call -> {"status":"already_processed","event_id":1}

docker compose logs notifications | tail -5
```

## Default Credentials

| Role  | Email                  | Password    | Source                       |
|-------|------------------------|-------------|------------------------------|
| Admin | `admin@postershop.com` | `admin1234` | `services/users/init_db.py`  |

These are seeded on first migration run. Change in production.
