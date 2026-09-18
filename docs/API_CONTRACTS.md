# Inter-Service API Contracts

This document defines the APIs used for service-to-service communication.

---

## Overview

| Caller | Callee | Purpose | Protocol |
|--------|--------|---------|----------|
| Orders | Inventory | Stock reservation/commit | Sync HTTP |
| Orders | Payments | Checkout sessions | Sync HTTP |
| Orders | Payments | Escrow contract deploy / state / courier / release / cancel (`/v1/escrow`) | Sync HTTP |
| Logistics | Orders | Courier wallet binding on pick-up (CONTRACT B) | Sync HTTP (fire-and-forget) |
| Orders (Outbox) | Production | Order events (ORDER_PAID, ORDER_CANCELLED) | Async HTTP |
| Orders (Outbox) | Notifications | Order events (all four types) — transactional email | Async HTTP |
| Orders (Outbox) | Designs | ORDER_PAID — `purchased_at` on bought designs, style-profile input | Async HTTP |
| Designs | Catalog | Print-this: create the unlisted `AI-{id}` family (`/internal/products`) | Sync HTTP |
| Designs | Inventory | Print-this: create the virtual stock rows (`/internal/stock`) | Sync HTTP |
| Production | Orders | Status updates | Sync HTTP |
| Production | Logistics | Create shipment | Sync HTTP |
| Logistics | Orders | Delivery notification | Sync HTTP |
| Catalog | Inventory | Stock check | Sync HTTP |
| Inventory | Orders | Reservation expiry notification | Sync HTTP (fire-and-forget) |
| Stripe (external) | Orders | `checkout.session.completed`, signature-verified | Async HTTP |

---

## Inventory Service APIs

### Reserve Stock

**Called by:** Orders Service  
**When:** Order is created

```http
POST /reserve
Content-Type: application/json

{
  "order_id": 123,
  "sku": "POSTER-SUNSET-A3",
  "quantity": 2,
  "ttl_minutes": 15
}
```

**Response (200 OK):**
```json
{
  "reservation_id": 456,
  "order_id": 123,
  "sku": "POSTER-SUNSET-A3",
  "quantity": 2,
  "status": "active",
  "expires_at": "2024-01-15T10:45:00Z"
}
```

**Error Responses:**
- `409 Conflict` - Insufficient stock
- `404 Not Found` - SKU not found

---

### Release Stock

**Called by:** Orders Service  
**When:** Order is cancelled

```http
POST /release
Content-Type: application/json

{
  "order_id": 123,
  "sku": "POSTER-SUNSET-A3"  // Optional, null releases all for order
}
```

**Response (200 OK):**
```json
{
  "released_count": 1,
  "released_quantity": 2
}
```

---

### Commit Stock

**Called by:** Orders Service  
**When:** Payment is successful

```http
POST /commit
Content-Type: application/json

{
  "order_id": 123,
  "sku": null  // null commits all reservations for order
}
```

**Response (200 OK):**
```json
{
  "committed_count": 2,
  "committed_quantity": 5
}
```

---

### Bulk Stock Check

**Called by:** Catalog Service  
**When:** Listing products with stock info

```http
POST /stock/check
Content-Type: application/json

{
  "skus": ["POSTER-SUNSET-A3", "POSTER-MOUNTAIN-A3"]
}
```

**Response (200 OK):**
```json
{
  "items": [
    {
      "sku": "POSTER-SUNSET-A3",
      "available": 50,
      "reserved": 5,
      "can_reserve": 45
    },
    {
      "sku": "POSTER-MOUNTAIN-A3",
      "available": 30,
      "reserved": 2,
      "can_reserve": 28
    }
  ]
}
```

### Create Virtual Stock (Internal)

**Called by:** Designs Service (`inventory_client.py`)  
**When:** "Print this" — after the catalog family exists, before the generation row is updated  
**Auth:** service token or owner bearer (`require_service_or_owner`)

```http
POST /internal/stock
Authorization: Bearer <service token>
Content-Type: application/json

{
  "items": [
    {"sku": "AI-28-A4", "name": "Custom: geometric lighthouse at dusk (A4)", "available": 1000},
    {"sku": "AI-28-A3", "name": "Custom: geometric lighthouse at dusk (A3)", "available": 1000},
    {"sku": "AI-28-A2", "name": "Custom: geometric lighthouse at dusk (A2)", "available": 1000},
    {"sku": "AI-28-A1", "name": "Custom: geometric lighthouse at dusk (A1)", "available": 1000}
  ]
}
```

**Response (200 OK):**
```json
{
  "created": ["AI-28-A4", "AI-28-A3", "AI-28-A2", "AI-28-A1"],
  "skipped": []
}
```

1..50 items per call. SKUs that already exist are **skipped, never 400**, so a caller can
retry after a partial failure and only the missing rows are added. The owner-only
`POST /stock` and the reservation logic are untouched — the AI SKUs are ordinary stock
rows with a large quantity (`AI_POSTER_STOCK`, "virtual stock" for print-on-demand).

---

## Catalog Service APIs (Internal)

### Create Product Family (Internal)

**Called by:** Designs Service (`catalog_client.py`)  
**When:** "Print this" on a ready design — the first of the two downstream writes  
**Auth:** service token or owner bearer (`require_service_or_owner`)

```http
POST /internal/products
Authorization: Bearer <service token>
Content-Type: application/json

{
  "sku": "AI-28",
  "name": "Custom: geometric lighthouse at dusk",
  "description": "integration test poster: geometric lighthouse at dusk",
  "category": "Custom",
  "image_url": "/api/designs/images/335b26e4a53f45ac8f40c1a6f6de9868.png",
  "listed": false,
  "active": true,
  "variants": [
    {"size": "A4", "price": "24.99"},
    {"size": "A3", "price": "29.99"},
    {"size": "A2", "price": "39.99"},
    {"size": "A1", "price": "54.99"}
  ]
}
```

**Response:** the family as `GET /products/{sku}` returns it (`ProductOut` with `listed`
and the four variants `AI-28-A4` … `AI-28-A1`).

| Status | Meaning |
|--------|---------|
| `201` | Family and every variant written in **one transaction** |
| `200` | `sku` already exists — answered with the family as it is, nothing written (idempotent retry) |
| `400` | Unknown size (not in `sizes`) or a duplicate size in `variants` — rejected before any write |

Variant SKUs are `{sku}-{size}`. `products.price` is set to the cheapest variant as the
motif's reference price and is never charged — orders prices through
`POST /internal/resolve-prices`, which is unchanged.

### Listing and the `listed` flag

`GET /products` takes `?listed_only=true|false` (default `true`) and hides unlisted
families — the custom AI motifs — from the shop grid; `GET /categories` never lists a
category whose only products are unlisted (so no empty "Custom" tab). `GET /products/{sku}`
and `POST /internal/resolve-prices` ignore the flag, so the studio's direct product link,
the cart and checkout work for an unlisted family exactly as for a listed one. The admin
table passes `listed_only=false`.

---

## Payments Service APIs

### Create Checkout Session

**Called by:** Orders Service  
**When:** Customer clicks "Pay"

```http
POST /v1/checkout/sessions
Content-Type: application/json

{
  "order_id": 123,
  "customer_email": "customer@example.com",
  "line_items": [
    {
      "name": "Golden Sunset - A3",
      "quantity": 2,
      "unit_amount": 2499  // cents
    }
  ],
  "success_url": "http://localhost:3000/success",
  "cancel_url": "http://localhost:3000/cancel"
}
```

**Response (200 OK):**
```json
{
  "id": "cs_test_abc123",
  "order_id": 123,
  "customer_email": "customer@example.com",
  "status": "open",
  "amount_total": 4998,
  "currency": "usd",
  "checkout_url": "http://localhost:8007/checkout/cs_test_abc123",
  "created_at": "2024-01-15T10:30:00Z",
  "expires_at": "2024-01-16T10:30:00Z"
}
```

---

### Get Checkout Session

**Called by:** Orders Service  
**When:** Checking existing session status

```http
GET /v1/checkout/sessions/{session_id}
```

**Response (200 OK):**
```json
{
  "id": "cs_test_abc123",
  "status": "complete",  // open, complete, expired
  "payment_intent_id": "pi_test_xyz789",
  "amount_total": 4998
}
```

---

### Escrow (Ethereum, `OrderEscrow` on Ganache)

**Called by:** Orders Service with a service token — except `/config` and `/demo-accounts`,
which are public reads the SPA makes before login  
**When:** An order was placed with `payment_method: "escrow"`

Payments drives one `OrderEscrow` contract per order on an Ethereum JSON-RPC node
(`ESCROW_RPC_URL`; Ganache in every environment so far) from the shop-owned key
`ESCROW_OWNER_PRIVATE_KEY`. Escrow state lives on chain and on the orders row, so payments
stays stateless. Every route below except `/config` and `/demo-accounts` carries
`require_service_or_owner`, and `{address}` must match `^0x[0-9a-fA-F]{40}$`
(`services/payments/main.py`, `services/payments/escrow.py`). The handlers are plain `def`:
web3 is synchronous and runs in FastAPI's threadpool.

```http
GET /v1/escrow/config
```

Public and never 503s: `enabled` is `false` (with `chain_id` and `owner_address` `null`)
when no owner key is configured or the chain is unreachable, so the SPA hides the Ether
option instead of failing.

**Response (200 OK):**
```json
{
  "rpc_url": "/rpc",
  "wei_per_usd": 1000000000000000,
  "courier_share_bps": 2000,
  "enabled": true,
  "chain_id": 1337,
  "owner_address": "0x..."
}
```

```http
GET /v1/escrow/demo-accounts
```

Public; `404` unless `ESCROW_EXPOSE_DEMO_ACCOUNTS` is true **and** the node identifies
as Ganache. Returns the ten deterministic accounts as
`[{"index": 0, "address": "0x...", "private_key": "0x..."}, ...]`.

```http
POST /v1/escrow
Content-Type: application/json

{
  "order_id": 123,
  "customer_address": "0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1",
  "amount_usd": "49.98"
}
```

Deploys the contract from the owner key; `amount_usd` is converted at `WEI_PER_USD`.

**Response (200 OK):**
```json
{
  "contract_address": "0x...",
  "deploy_tx_hash": "0x...",
  "amount_wei": "49980000000000000"
}
```

```http
GET /v1/escrow/{address}
```

Live chain state: `{state, owner, customer, courier, price_wei, balance_wei}`. `state` is
one of `awaiting_payment`, `funded`, `in_delivery`, `released`, `cancelled`; `courier` is
`null` until bound; the wei fields are decimal strings because 10^18 does not fit a JSON
number.

```http
GET /v1/escrow/{address}/invoice
```

The unsigned `pay()` transaction the customer's wallet signs and sends:
`{to, value, data, chain_id}` (`value` is a decimal string; ethers fills nonce and gas).

```http
POST /v1/escrow/{address}/courier
Content-Type: application/json

{
  "courier_address": "0x22d491bde2303f2f43325b2108d26f1eaba1e32b"
}
```

`assignCourier()` from the owner key; the contract must be `funded`.

```http
POST /v1/escrow/{address}/release
```

`confirmDelivery()`: pays the courier `ESCROW_COURIER_SHARE_BPS` of the price and the
owner the rest, then closes the contract. Reverts with `"Delivery not complete."` when no
courier was ever bound.

```http
POST /v1/escrow/{address}/cancel
```

`cancel()`: refunds the customer if the contract is funded, then closes it.

`courier`, `release` and `cancel` all answer:
```json
{
  "tx_hash": "0x...",
  "state": "in_delivery"  // the contract state after the transaction
}
```

**Error Responses (shared by every escrow route except `/config`):**
- `409 Conflict` - the contract reverted; `detail` is the bare `require` reason
  (`"Only owner."`, `"Order closed."`, `"Transfer not complete."`,
  `"Delivery not complete."`, `"Cannot cancel."`, ...)
- `404 Not Found` - no contract code at `{address}`
- `503 Service Unavailable` - `"Escrow unavailable: ..."` — the chain is down or no owner
  key is configured (`/config` answers `enabled: false` instead of 503)

---

## Orders Service APIs (Internal)

### Update Order Status

**Called by:** Production Service, Logistics Service  
**When:** Order progresses through lifecycle

```http
POST /orders/{order_id}/produce
POST /orders/{order_id}/ship
POST /orders/{order_id}/deliver
```

`POST /orders/{id}/ship` and `POST /orders/{id}/deliver` also emit `ORDER_SHIPPED` and
`ORDER_DELIVERED` respectively, written to the outbox **in the same transaction as the
status change**. Either both the status change and the event persist, or neither does —
the status can never advance without its notification event being queued.

**Response (200 OK):**
```json
{
  "id": 123,
  "status": "producing",
  "customer_email": "customer@example.com",
  "total_amount": "49.98",
  "items": [...]
}
```

**Error Responses:**
- `400 Bad Request` - Invalid state transition
- `404 Not Found` - Order not found

### Reservation Expired

**Called by:** Inventory Service (expiry worker)
**When:** A stock reservation passes its 15-minute TTL and the worker releases it

```http
POST /internal/orders/{order_id}/reservation-expired
Content-Type: application/json

{}
```

The inventory worker (`services/inventory/main.py`) posts this with a 5-second timeout
after it has already returned the stock to the free pool. The call is fire-and-forget:
inventory swallows every exception and only logs a warning on a transport failure or a
`>= 400` response, because the stock release has already succeeded and a missed
notification is a non-fatal divergence rather than a lost update. It fires only on the
worker tick that actually flipped the reservation to `expired`, so later ticks do not
re-send it.

This endpoint takes `require_service_or_owner`: the caller mints a short-lived token carrying `role="service"` (see `services/shared/service_auth.py`). It is service-to-service traffic, but the ALB makes it internet-reachable, so it is not left open
network, reachable only from inside the cluster.

**Response — always `200 OK`.** The handler is deliberately idempotent and never returns
4xx or 5xx, because duplicate, unknown and wrong-state calls are all expected rather than
errors:

| Condition | Body |
|-----------|------|
| Order not found | `{"status": "not_found", "order_id": ...}` |
| Order not in `reserved` | `{"status": "no_action", "current_status": ...}` |
| Order in `reserved` | Order flips to `cancelled` and an `ORDER_CANCELLED` event is written to the outbox |

For an escrow order this path also cancels the open `OrderEscrow` contract (refunding the
customer if it was funded) and reports the outcome as `escrow_refunded` in the event payload.

### Courier Binding (CONTRACT B)

**Called by:** Logistics Service (background task on the pick-up transition)  
**When:** A shipment moves `dispatched -> in_transit` and a courier wallet is known — the
one in the `PUT /shipments/{id}/status` body, else `LOGISTICS_DEFAULT_COURIER_WALLET`

```http
POST /internal/orders/{order_id}/courier
Content-Type: application/json

{
  "courier_wallet": "0x22d491bde2303f2f43325b2108d26f1eaba1e32b"
}
```

Takes `require_service_or_owner` like the reservation-expired callback. Logistics posts
it fire-and-forget (`orders_client.notify_courier_assigned`), so the handler is
idempotent and **always answers `200 OK`**; the escrow reconciler retries anything that
could not be completed on chain from the stored wallet.

| `status` | Meaning |
|----------|---------|
| `not_found` | No such order — no-op |
| `stored` | Wallet saved on the order; not an escrow order (or no contract yet) |
| `already_bound` | `escrow_status` is already `in_delivery` or `released` |
| `bound` | Wallet saved **and** `assignCourier()` succeeded on chain — `escrow_status` becomes `in_delivery` |
| `deferred` | Wallet saved but payments/chain unavailable or the contract is not yet funded — `escrow_status` unchanged, the reconciler retries |

**Response (200 OK):**
```json
{
  "status": "bound",
  "order_id": 123,
  "escrow_status": "in_delivery"
}
```

### Escrow (customer-facing, listed for completeness)

Not service-to-service — the SPA calls these with the customer's JWT (owner too; `GET`
also for a courier) — but they are the orders-side half of the payments escrow contract
above:

```http
POST /orders/{order_id}/escrow
GET /orders/{order_id}/escrow
POST /orders/{order_id}/escrow/verify
POST /orders/{order_id}/escrow/confirm-delivery
```

- `POST /orders/{id}/escrow` — deploy (or resume): the order must be `reserved` and carry
  `customer_wallet`; deploys through `POST /v1/escrow` exactly once and returns the
  contract address, the `pay()` invoice and the chain config. `POST /orders/{id}/checkout`
  answers `400` for an escrow order.
- `GET /orders/{id}/escrow` — the stored row plus the live chain state (`chain`,
  `chain_error` when payments cannot be reached).
- `POST /orders/{id}/escrow/verify` — reads the chain; when the contract is funded it runs
  `order_paid.mark_order_paid`, the **same path as the Stripe webhook** (commit stock,
  `paid`, `ORDER_PAID`). Idempotent; `409` when the contract vanished from the chain
  (`escrow_status` -> `failed`).
- `POST /orders/{id}/escrow/confirm-delivery` — the customer confirms receipt; the order
  must be `delivered`; payments sends `confirmDelivery()` from the owner key. `409` with
  the contract reason (e.g. `"Delivery not complete."` when no courier was bound).

---

## Production Service APIs

### Event Handlers (Outbox Consumers)

**Called by:** Orders Service Outbox Worker

#### ORDER_PAID Event

```http
POST /events/order-paid
Content-Type: application/json

{
  "event_id": 42,
  "event_type": "ORDER_PAID",
  "aggregate_type": "order",
  "aggregate_id": "123",
  "payload": {
    "order_id": 123,
    "customer_email": "customer@example.com",
    "total_amount": "49.98",
    "items": [
      {"sku": "POSTER-SUNSET-A3", "name": "Golden Sunset", "quantity": 2}
    ]
  },
  "created_at": "2024-01-15T10:30:00Z"
}
```

**Response (200 OK):**
```json
{
  "status": "created",  // or "already_exists" for idempotency
  "job_id": 456
}
```

#### ORDER_CANCELLED Event

```http
POST /events/order-cancelled
Content-Type: application/json

{
  "event_id": 43,
  "event_type": "ORDER_CANCELLED",
  "aggregate_type": "order",
  "aggregate_id": "123",
  "payload": {
    "order_id": 123,
    "customer_email": "customer@example.com",
    "previous_status": "reserved",
    "released_stock": true,
    "reason": "cancelled by customer"
  }
}
```

**Response (200 OK):**
```json
{
  "status": "cancelled",  // or "no_job" or "already_processing"
  "job_id": 456
}
```

---

## Notifications Service APIs

**Called by:** Orders Service (outbox worker)  
**When:** Any order-lifecycle event occurs

Stateless service — no database. Not ALB-exposed; reached over cluster-internal DNS only.

### Event Handlers

```http
POST /events/order-paid
POST /events/order-shipped
POST /events/order-delivered
POST /events/order-cancelled
```

All four accept the standard outbox envelope:

```json
{
  "event_id": 42,
  "event_type": "ORDER_PAID",
  "aggregate_type": "order",
  "aggregate_id": "123",
  "payload": {
    "order_id": 123,
    "customer_email": "customer@example.com",
    "total_amount": "99.99",
    "items": [...]
  },
  "created_at": "2026-07-05T10:30:00Z"
}
```

`payload.customer_email` is the only field the service strictly requires.

### Response Contract

**The status code is load-bearing**, because it directly controls whether the orders
outbox worker retries the event. Getting it wrong either drops customer email silently or
floods the retry budget.

| Response | Meaning | Why this code |
|----------|---------|---------------|
| `200 {"status": "sent", "event_id": 42}` | Email handed to the provider | Success; outbox marks the event delivered |
| `200 {"status": "already_processed", "event_id": 42}` | This `event_id` was seen before | Duplicate delivery is expected under at-least-once semantics and is not an error |
| `200 {"status": "skipped", "reason": "no_customer_email"}` | Payload carried no address | **Deliberately 200, not 4xx.** Retrying cannot make a missing address appear, so a non-2xx here would burn all five delivery attempts and then abandon the event for no reason |
| `503` | The email provider raised on send | **Deliberately retryable.** A transient SES failure should be retried with backoff, so the event is left undelivered and the worker tries again |

The distinction reduces to: **200 means "do not retry, there is nothing more to do";
503 means "retry, this might succeed later."** The service returns `200` for the skip
case precisely so that a permanently unfixable input does not consume the retry budget.

### Idempotency

Guarded by the durable `notifications_schema.processed_events` table, keyed by `event_id`
(`services/notifications/main.py`): select first, send, then record with
`INSERT ... ON CONFLICT DO NOTHING`. Dedup survives restarts and is shared across
replicas. The residual window is send-then-record — a crash between the two re-sends the
mail on redelivery (see `docs/KNOWN_LIMITATIONS.md` #3).

### Health & Metrics

```http
GET /healthz    # liveness
GET /readyz     # readiness — SELECT 1, returns 503 when the database is unreachable
GET /metrics    # Prometheus
```

---

## Designs Service APIs

The AI poster studio. Customer routes are called by the shop through the `/api/designs`
proxy (nginx / ALB); one route is an outbox consumer. Full route table in
[services/designs/README.md](../services/designs/README.md).

### Queue a Generation

**Called by:** Frontend (`/shop/studio`)  
**Auth:** customer bearer

```http
POST /generations
Authorization: Bearer <token>
Content-Type: application/json

{
  "prompt": "a minimalist travel poster of Belgrade at dawn",
  "personalise": true
}
```

**Response (202 Accepted):**
```json
{
  "id": 28,
  "prompt": "a minimalist travel poster of Belgrade at dawn",
  "effective_prompt": "a minimalist travel poster of Belgrade at dawn",
  "personalise": true,
  "provider": "fake",
  "status": "queued",
  "failure_reason": null,
  "image_url": null,
  "created_at": "2026-09-18T06:30:31Z",
  "started_at": null,
  "finished_at": null,
  "purchased_at": null,
  "catalog_product_sku": null,
  "product_url": null
}
```

`prompt` is 3..2000 characters. Over the daily quota (`AI_DAILY_QUOTA`, per UTC day, owner
exempt) the answer is `429 {"detail": "Daily limit of 10 generations reached"}` with a
`Retry-After` header counting down to UTC midnight.

### Poll a Generation

```http
GET /generations/{id}
Authorization: Bearer <token>
```

**Response (200 OK)** — the same shape, filled in as the worker progresses:

| `status` | What is set |
|----------|-------------|
| `queued` | nothing yet (`retry_after` in the DB when a transport failure is backing off) |
| `generating` | `started_at`, `attempts` consumed |
| `ready` | `image_url` = `/api/designs/images/{32 hex}.png`, `finished_at`; `effective_prompt` carries the `Style notes:` suffix when personalised |
| `failed` | `failure_reason` — the provider's refusal text, or a generic outage / configuration message |

Someone else's `id` is a `404`, indistinguishable from a missing one. `GET /generations`
lists the caller's rows newest first (`?limit=` 1..200).

### Image

```http
GET /images/{key}          # key = 32 hex + .png, no bearer (the key is the capability)
HEAD /images/{key}
```

`200 image/png` with `Cache-Control: public, max-age=31536000, immutable` and an `ETag`;
`422` for a malformed key, `404` for an unknown one.

### Print This

```http
POST /generations/{id}/print
Authorization: Bearer <token>
```

**Response (201 Created / 200 OK):**
```json
{
  "sku": "AI-28",
  "product_url": "/shop/product/AI-28",
  "created": true
}
```

| Status | Meaning |
|--------|---------|
| `201` | Catalog family `AI-28` (variants `AI-28-A4` … `AI-28-A1`) and four stock rows created now |
| `200` | Already printed — same payload with `created: false` |
| `409` | The generation is not `ready` |
| `502` | Catalog or inventory refused (4xx) — the detail is passed through |
| `503` | Catalog or inventory unavailable, or their circuit breaker is open — retry later |

Orchestration is catalog → inventory → own row; each downstream write is idempotent, so a
`503` half-way leaves `catalog_product_sku` NULL and the retry completes the missing half.

### Style Profile

```http
GET /me/style-profile
POST /me/style-profile/refresh
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "summary": "You lean towards: dusk, travel, belgrade, lighthouse, harbour, smoke.",
  "prompt_count": 13,
  "purchase_count": 1,
  "stale": false,
  "updated_at": "2026-09-18T06:09:14Z"
}
```

A customer without a profile row gets the defaults (`summary: null`, counts 0,
`stale: true`) — not a 404. `refresh` rebuilds the summary from the last 20 prompts and 20
purchase names through the summariser (`gpt-4o-mini` with a key, deterministic keywords
otherwise); a summariser outage keeps the old summary and answers 200 with `stale: true`.

### Event Handler (Outbox Consumer)

**Called by:** Orders Service (outbox worker) — the third `ORDER_PAID` subscriber  
**Auth:** service token or owner bearer (`require_service_or_owner`)

```http
POST /events/order-paid
Authorization: Bearer <service token>
Content-Type: application/json

{
  "event_id": 197,
  "event_type": "ORDER_PAID",
  "aggregate_type": "order",
  "aggregate_id": "832",
  "payload": {
    "order_id": 832,
    "customer_email": "customer@example.com",
    "total_amount": "29.99",
    "items": [{"sku": "AI-23-A3", "name": "Custom: … (A3)", "quantity": 1}]
  },
  "created_at": "2026-09-18T06:08:58Z"
}
```

| Response | Meaning |
|----------|---------|
| `200 {"status": "processed", "event_id": 197, "own_designs": 1, "purchases": 1}` | Own `AI-{id}-{size}` SKUs got `purchased_at` (once), every item became a `purchases` row, the profile is marked stale, the event id recorded |
| `200 {"status": "already_processed", "event_id": 197}` | Duplicate `event_id` — nothing touched |
| `200 {"status": "skipped", "reason": "no_customer_email", "event_id": 197}` | Nothing to attribute — deliberately 200, retrying cannot help |

The handler is DB-only (never calls a provider) and answers well inside the outbox's 10 s
budget; a non-2xx would make the outbox re-deliver the event to production and
notifications as well, so business cases never 5xx. Dedup is durable in
`designs_schema.processed_events` (`INSERT … ON CONFLICT DO NOTHING`).

### Health & Metrics

```http
GET /healthz    # liveness
GET /readyz     # readiness — opens a DB connection, 503 when unreachable
GET /metrics    # Prometheus: designs_generations_total, designs_provider_latency_seconds, designs_queue_depth, circuit_breaker_state_transitions_total
```

---

## Logistics Service APIs

### Create Shipment

**Called by:** Production Service  
**When:** Production is complete

```http
POST /ship
Content-Type: application/json

{
  "order_id": 123
}
```

**Response (200 OK):**
```json
{
  "shipment_id": 789,
  "tracking": "TRK-000123"
}
```

---

## Webhook: Stripe → Orders

### checkout.session.completed

**Called by:** Stripe (external — not the payments service)  
**When:** Customer completes payment on Stripe's hosted checkout page

```http
POST /webhooks/stripe
Content-Type: application/json
Stripe-Signature: t=1234567890,v1=abc123...

{
  "id": "evt_test_123",
  "object": "event",
  "type": "checkout.session.completed",
  "data": {
    "object": {
      "id": "cs_test_abc123",
      "object": "checkout.session",
      "payment_status": "paid",
      "payment_intent": "pi_test_xyz789",
      "amount_total": 4998,
      "customer_email": "customer@example.com",
      "metadata": {
        "order_id": "123"
      }
    }
  }
}
```

**Response (200 OK):**
```json
{
  "received": true,
  "order_id": 123,
  "new_status": "paid"
}
```

`checkout.session.completed` (`services/orders/stripe_webhook.py`) and escrow
`POST /orders/{id}/escrow/verify` share one code path: `order_paid.mark_order_paid`
commits the stock, sets `paid` and emits `ORDER_PAID` in a single transaction, so a card
order and an Ether order become `paid` through exactly the same function.

---

## Error Response Format

All services use consistent error format:

```json
{
  "detail": "Human-readable error message"
}
```

**Common HTTP Status Codes:**
- `400 Bad Request` - Invalid input
- `404 Not Found` - Resource not found
- `409 Conflict` - Business rule violation (e.g., insufficient stock)
- `503 Service Unavailable` - Downstream service unavailable

---

## Timeouts & Retries

| Call Type | Timeout | Retry Policy |
|-----------|---------|--------------|
| Stock reservation | 5s connect, 10s total | No retry (fail order) |
| Stock commit | 5s connect, 10s total | Retry 3x with backoff |
| Payment create | 5s connect, 10s total | No retry |
| Event delivery | 5s connect, 10s total | 5x with exponential backoff (per event — designs' `/events/order-paid` must answer inside the 10 s, so it is DB-only) |
| Print-this: catalog `/internal/products`, inventory `/internal/stock` | 5s connect, 10s total | No retry inside the request (circuit breaker per destination); the customer retries the idempotent `POST /generations/{id}/print` |
| Image provider (designs worker) | 180s per call (OpenAI / Replicate) | 3 attempts (`DESIGNS_MAX_ATTEMPTS`), waiting 5 s / 30 s / 120 s; an open breaker re-queues without consuming an attempt |
| Status updates | 5s connect, 10s total | Best effort (logged) |

---

## Health Check Contract

All services expose:

```http
GET /healthz
```

**Response (200 OK):**
```json
{
  "status": "ok",
  "service": "service-name"
}
```

Used by Kubernetes liveness/readiness probes.
