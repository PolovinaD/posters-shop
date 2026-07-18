# Orders Service

Order lifecycle management with outbox pattern for reliable event delivery.

## Purpose

- Create and manage customer orders
- Coordinate stock reservation with inventory
- Handle payment flow with Stripe (mock)
- Emit events via transactional outbox pattern

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- httpx (inter-service calls)
- asyncio (outbox worker)
- Prometheus metrics

## Database Schema

**Schema:** `orders_schema`

### orders
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| customer_email | VARCHAR | Customer email |
| status | VARCHAR | Order status |
| total_amount | NUMERIC(10,2) | Order total |
| checkout_session_id | VARCHAR | Stripe session ID |
| payment_intent_id | VARCHAR | Stripe payment intent |
| created_at | TIMESTAMP | Order created |
| updated_at | TIMESTAMP | Last update |

### order_items
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| order_id | INTEGER | FK to orders |
| sku | VARCHAR | Product SKU |
| name | VARCHAR | Product name |
| quantity | INTEGER | Quantity |
| unit_price | NUMERIC(10,2) | Price per unit |

### outbox_events
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| event_type | VARCHAR | Event name |
| aggregate_type | VARCHAR | Entity type |
| aggregate_id | VARCHAR | Entity ID |
| payload | TEXT | JSON payload |
| delivered_at | TIMESTAMP | Delivery time |
| retry_count | INTEGER | Retry attempts |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /orders | Create order | - |
| GET | /orders | List orders | - |
| GET | /orders/{id} | Get order | - |
| POST | /orders/{id}/pay | Mark as paid | Internal |
| POST | /orders/{id}/produce | Start production | Internal |
| POST | /orders/{id}/ship | Mark shipped | Internal |
| POST | /orders/{id}/deliver | Mark delivered | Internal |
| POST | /orders/{id}/cancel | Cancel order | - |
| POST | /orders/{id}/checkout | Create payment session | - |
| GET | /orders/{id}/checkout-status | Get payment status | - |
| POST | /webhooks/stripe | Stripe webhook | - |
| GET | /outbox/stats | Outbox monitoring | Admin |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| INVENTORY_SERVICE_URL | Inventory service | `http://inventory:8000` |
| PRODUCTION_SERVICE_URL | Production service | `http://production:8000` |
| PAYMENT_SERVICE_URL | Payment service | `http://payments:8000` |
| STRIPE_WEBHOOK_SECRET | Webhook verification | `whsec_test...` |

## Local Development

```bash
cd services/orders
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8004
```

## Order Status Flow

```
created ──> reserved ──> paid ──> producing ──> shipped ──> delivered
    │           │          │
    └───────────┴──────────┴──────> cancelled/failed
```

## Events Produced

| Event | Trigger | Consumers |
|-------|---------|-----------|
| ORDER_PAID | Payment webhook received | Production, Notifications |
| ORDER_CANCELLED | Order cancelled | Production, Notifications |
| ORDER_SHIPPED | `POST /orders/{id}/ship` | Notifications |
| ORDER_DELIVERED | `POST /orders/{id}/deliver` | Notifications |

`ORDER_PAID` and `ORDER_CANCELLED` fan out to two subscribers each, so the outbox
is publish-subscribe rather than a single-consumer channel. See
[docs/EVENT_CATALOG.md](../../docs/EVENT_CATALOG.md) for payloads and the
authoritative `EVENT_SUBSCRIBERS` map (`outbox.py:36-51`).

## Outbox Pattern

1. Events written to `outbox_events` in same transaction as order update
2. Background worker polls every 2 seconds
3. Delivers via HTTP POST to subscribers
4. Marks delivered or schedules retry (max 5 attempts)
5. Exponential backoff: 5s, 15s, 1m, 5m, 15m

## Dependencies

- **Inventory Service**: Stock reservation/commit
- **Payments Service**: Checkout session creation
- **Production Service**: Event consumer (async)
