# Inventory Service

Stock management with reservation system and automatic expiry.

## Purpose

- Track available and reserved stock per SKU
- Handle stock reservations for orders
- Automatic reservation expiry (TTL-based)
- Commit reservations on payment success

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- asyncio (background worker)
- Prometheus metrics

## Database Schema

**Schema:** `inventory_schema`

### stock
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| sku | VARCHAR | Unique stock keeping unit |
| name | VARCHAR | Item name |
| available | INTEGER | Available quantity |
| reserved | INTEGER | Reserved quantity |
| created_at | TIMESTAMP | Record creation |
| updated_at | TIMESTAMP | Last update |

### reservations
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| order_id | INTEGER | Associated order |
| sku | VARCHAR | Reserved SKU |
| quantity | INTEGER | Reserved quantity |
| status | VARCHAR | active, released, expired, committed |
| expires_at | TIMESTAMP | TTL expiration time |
| released_at | TIMESTAMP | When status changed |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /stock | List all stock | - |
| GET | /stock/{sku} | Get stock for SKU | - |
| POST | /stock | Create stock item | Admin |
| PUT | /stock/{sku} | Update stock | Admin |
| POST | /stock/check | Bulk stock check | - |
| POST | /reserve | Reserve stock | Internal |
| POST | /release | Release reservation | Internal |
| POST | /commit | Commit reservation | Internal |
| GET | /reservations | List reservations | Admin |
| POST | /seed | Seed sample data | Admin |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |

## Local Development

```bash
cd services/inventory
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8003
```

## Reservation Lifecycle

```
POST /reserve (order_id, sku, quantity, ttl_minutes)
    │
    ├── Stock available? ──No──> 409 Conflict
    │
    └── Yes
        │
        ├── Decrease available
        ├── Increase reserved
        └── Create reservation (status=active, expires_at=now+TTL)
            │
            ├── Order cancelled ──> POST /release
            │   └── Return to available, status=released
            │
            ├── Payment success ──> POST /commit
            │   └── Decrease reserved, status=committed
            │
            └── TTL expires (background worker)
                └── Return to available, status=expired
```

## Background Worker

The `expire_reservations_worker` runs every 30 seconds:
1. Finds active reservations where `expires_at < now`
2. Returns quantity to available stock
3. Marks reservation as `expired`
4. Updates Prometheus metrics

## Metrics

- `inventory_stock_level{sku}`: Current available stock
- `inventory_active_reservations`: Count of active reservations
- `inventory_reservations_expired_total`: Expired reservation counter

## Events

None - this service doesn't produce or consume events (sync API only).

## Dependencies

- None (standalone service, called by Orders and Catalog)
