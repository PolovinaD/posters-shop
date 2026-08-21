# Orders Service

Order lifecycle management with outbox pattern for reliable event delivery.

## Purpose

- Create and manage customer orders
- Coordinate stock reservation with inventory
- Handle payment flow with real Stripe Hosted Checkout — the session is created through the payments service, and Stripe posts the signed `checkout.session.completed` webhook back here at `/webhooks/stripe`, verified with `stripe.Webhook.construct_event` (`stripe_webhook.py`)
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
| POST | /orders | Create order | Auth — `customer_email` comes from the JWT `sub`, never the body |
| GET | /orders | List orders | Auth |
| GET | /orders/{id} | Get order | Auth + ownership (owner/courier any; customer only their own) |
| POST | /orders/{id}/pay | Mark as paid (bypasses Stripe) | **Owner** (`require_owner`) |
| POST | /orders/{id}/produce | Start production | Internal (service-to-service, no JWT) |
| POST | /orders/{id}/ship | Mark shipped | Internal (service-to-service, no JWT) |
| POST | /orders/{id}/deliver | Mark delivered | Internal (service-to-service, no JWT) |
| POST | /orders/{id}/cancel | Cancel order | Auth + ownership |
| POST | /orders/{id}/checkout | Create payment session | Auth + ownership |
| GET | /orders/{id}/checkout-status | Get payment status | Auth + ownership |
| GET | /orders/stats/by-status | Order counts per status | Auth |
| POST | /webhooks/stripe | Stripe webhook | Stripe signature (`stripe.Webhook.construct_event`) |
| POST | /internal/orders/{order_id}/reservation-expired | Inventory reports an expired reservation | Internal (no JWT; idempotent, always 200) |
| GET | /outbox/stats | Outbox monitoring | **Owner** (`require_owner`) |

`/produce`, `/ship` and `/deliver` carry no auth dependency because the
production and logistics workers call them with no JWT — adding one would stop
the pipeline. They are reachable through the ALB, so this is an open item
awaiting a service-token design, not a decision that they need no protection.

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
5. Exponential backoff between the 5 attempts: 5s, 15s, 1m, 5m (`RETRY_DELAYS` has a fifth 15m value that is never reached)

## Dependencies

- **Inventory Service**: Stock reservation/commit
- **Payments Service**: Checkout session creation
- **Production Service**: Event consumer (async)
