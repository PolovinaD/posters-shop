# Orders Service

Order lifecycle management with outbox pattern for reliable event delivery.

## Purpose

- Create and manage customer orders
- Coordinate stock reservation with inventory
- Handle payment flow with real Stripe Hosted Checkout — the session is created through the payments service, and Stripe posts the signed `checkout.session.completed` webhook back here at `/webhooks/stripe`, verified with `stripe.Webhook.construct_event` (`stripe_webhook.py`)
- Handle the Ethereum escrow alternative — one `OrderEscrow` contract per order deployed through payments, verified against the chain, and reconciled by a background worker (`## Escrow` below)
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
| payment_intent_id | VARCHAR | Stripe payment intent (escrow orders: the contract address) |
| payment_method | VARCHAR | `stripe` or `escrow`; NOT NULL, server default `stripe` (`003_escrow.py`) |
| customer_wallet | VARCHAR(42) | Customer's Ethereum address (escrow only) |
| courier_wallet | VARCHAR(42) | Courier payout address stored on pick-up (CONTRACT B) |
| escrow_contract_address | VARCHAR(42) | The order's `OrderEscrow` contract |
| escrow_deploy_tx | VARCHAR(66) | Deploy transaction hash |
| escrow_amount_wei | VARCHAR | Price in wei as a decimal string on purpose — 10^18 does not fit a JS number |
| escrow_status | VARCHAR | `EscrowStatus` mirror, indexed (`ix_orders_escrow_status`) — the reconciler polls open rows |

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
| POST | /orders/{id}/produce | Start production | Service or owner (`require_service_or_owner`) |
| POST | /orders/{id}/ship | Mark shipped | Service or owner (`require_service_or_owner`) |
| POST | /orders/{id}/deliver | Mark delivered | Service or owner (`require_service_or_owner`) |
| POST | /orders/{id}/cancel | Cancel order | Auth + ownership |
| POST | /orders/{id}/checkout | Create payment session — answers **400** for an escrow order (use `/escrow`) | Auth + ownership |
| GET | /orders/{id}/checkout-status | Get payment status | Auth + ownership |
| POST | /orders/{id}/escrow | Deploy (or resume) the order's `OrderEscrow`; order must be `reserved` with a `customer_wallet`; idempotent | Auth + ownership |
| GET | /orders/{id}/escrow | Stored escrow row + live chain state (`chain`, `chain_error`) | Auth + ownership (courier too) |
| POST | /orders/{id}/escrow/verify | Read the chain; funded -> `mark_order_paid` (same path as the Stripe webhook); 409 if the contract vanished | Auth + ownership |
| POST | /orders/{id}/escrow/confirm-delivery | Customer confirms receipt on a `delivered` order -> payments `confirmDelivery()`; 409 with the contract reason | Auth + ownership |
| GET | /orders/stats/by-status | Order counts per status | Auth |
| POST | /webhooks/stripe | Stripe webhook | Stripe signature (`stripe.Webhook.construct_event`) |
| POST | /internal/orders/{order_id}/reservation-expired | Inventory reports an expired reservation (also cancels an open escrow contract) | Service or owner; idempotent, always 200 |
| POST | /internal/orders/{order_id}/courier | CONTRACT B — logistics sends `{courier_wallet}` on pick-up; `status` ∈ bound / stored / already_bound / deferred / not_found | Service or owner; idempotent, always 200 |
| GET | /outbox/stats | Outbox monitoring | **Owner** (`require_owner`) |

The ALB routes `/api/orders` straight to this Service, so every route here is
internet-reachable. The routes only another service should call therefore take
`require_service_or_owner` (`service_auth.py`): callers mint a short-lived token
carrying `role="service"`, signed with the `JWT_SECRET` the platform already
distributes. Owner is accepted too, so an operator can drive them by hand and the
admin dashboard keeps working.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| INVENTORY_SERVICE_URL | Inventory service | `http://inventory:8000` |
| PRODUCTION_SERVICE_URL | Production service | `http://production:8000` |
| PAYMENT_SERVICE_URL | Payment service | `http://payments:8000` |
| STRIPE_WEBHOOK_SECRET | Webhook verification | `whsec_test...` |
| ESCROW_RECONCILE_INTERVAL | Seconds between escrow reconciler passes (one worker per replica) | `15` |

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
| ORDER_PAID | `mark_order_paid` (`order_paid.py`) — from the Stripe webhook, escrow verify or the escrow reconciler | Production, Notifications |
| ORDER_CANCELLED | Order cancelled (payload carries `escrow_refunded`: true when an open contract was cancelled/refunded on the way) | Production, Notifications |
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

## Escrow

An order created with `payment_method: "escrow"` and a `customer_wallet` pays into one
`OrderEscrow` contract instead of a Stripe session. Orders is the source of truth for
escrow state; payments talks to the chain.

- `order_paid.py` — `mark_order_paid(db, order, payment_ref)`: the one place an order
  becomes `paid` from a verified payment (commit stock, `paid`, `ORDER_PAID`, one
  transaction). Shared by the Stripe webhook, `POST /orders/{id}/escrow/verify` and the
  reconciler; **not** by the owner-only `POST /orders/{id}/pay`. Returns `False` when
  already paid; an inventory commit failure is logged and the payment still honoured.
- `escrow_reconciler.py` — `escrow_reconciler_worker`, started in the lifespan, one per
  replica, every `ESCROW_RECONCILE_INTERVAL` s. Closes the gaps a browser or an outage
  leaves: paid on chain but the tab died before verify; a courier reported while payments
  was down or before funding; a refund that failed on cancel/expiry.
- `escrow_rules.py` — `decide_reconcile_action` returns one of `mark_failed`, `refund`,
  `mark_paid`, `sync_in_delivery`, `bind_courier`, `noop` from the stored row and the
  chain state; pure, unit-tested.
- `payment_client.py` — `create_escrow`, `get_escrow_state`, `get_escrow_invoice`,
  `assign_escrow_courier`, `release_escrow`, `cancel_escrow`, `get_escrow_config`; a
  contract revert surfaces as `EscrowRejectedError` with the bare reason.
- `models.py` — `PaymentMethod` {`stripe`, `escrow`}; `EscrowStatus` {`awaiting_payment`,
  `funded`, `in_delivery`, `released`, `cancelled`, `failed`}, `OPEN = (awaiting_payment,
  funded)` — the states in which `cancel()` refunds. `failed` is local only (contract gone).

## Dependencies

- **Inventory Service**: Stock reservation/commit
- **Payments Service**: Checkout session creation and every escrow chain call
- **Production Service**: Event consumer (async)
