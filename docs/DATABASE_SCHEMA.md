# Database Schema Documentation

## Overview

The platform uses a single PostgreSQL database with **schema-per-service** isolation. Each service owns its own schema and cannot access other schemas (enforced by convention, not database permissions).

**Database:** PostgreSQL 15+  
**Pattern:** Schema-per-service (logical isolation)

---

## Schema List

| Schema | Service | Tables |
|--------|---------|--------|
| `users_schema` | Users | users |
| `catalog_schema` | Catalog | products, sizes, frame_options |
| `inventory_schema` | Inventory | stock, reservations |
| `orders_schema` | Orders | orders, order_items, outbox_events |
| `production_schema` | Production | jobs |
| `logistics_schema` | Logistics | shipments |
| `notifications_schema` | Notifications | processed_events |
| `designs_schema` | Designs | generations, saved_prompts, style_profiles, purchases, processed_events |

**Two services are stateless and own no schema:** `payments` (checkout sessions live
at Stripe) and `infra` (reads live Kubernetes state). They have no Alembic migrations and
appear nowhere in this document. `notifications` was a third until it was given durable
idempotency: it now owns `notifications_schema`, has its own Alembic migration, and is
documented below. `designs` (the AI poster studio) owns `designs_schema` from its first
commit; generated images are NOT in the database — they live on a volume or in S3, and
`generations.image_key` is the pointer.

---

## users_schema

### users

Stores user accounts and authentication data.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | User ID |
| email | VARCHAR | UNIQUE, NOT NULL, INDEX | Email address (login identifier) |
| password_hash | VARCHAR | NOT NULL | Bcrypt password hash |
| role | VARCHAR | NOT NULL | Role: customer, owner, courier |
| first_name | VARCHAR | NULLABLE | First name |
| last_name | VARCHAR | NULLABLE | Last name |
| wallet_address | VARCHAR(42) | NULLABLE | Ethereum wallet (`0x` + 40 hex), set via `PUT /users/me/wallet`; couriers are paid to it (`003_wallet_address.py`) |

**Indexes:**
- `ix_users_email` (UNIQUE) on email

---

## catalog_schema

### products

Product catalog for the shop.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Product ID |
| sku | VARCHAR | UNIQUE, NOT NULL, INDEX | Stock Keeping Unit |
| name | VARCHAR | NOT NULL | Product name |
| description | TEXT | NULLABLE | Product description |
| price | NUMERIC(10,2) | NOT NULL | Base price |
| category | VARCHAR | NOT NULL | Category name |
| image_url | VARCHAR | NULLABLE | Product image URL |
| sizes | VARCHAR | NULLABLE | Available sizes (comma-separated) |
| active | BOOLEAN | DEFAULT true | Is product active |
| listed | BOOLEAN | NOT NULL, DEFAULT true | Shown in the public grid and category tabs (migration 003). Custom AI motifs created by designs' "Print this" are `false`: reachable by SKU, cart and `/internal/resolve-prices`, hidden from `GET /products` (default `listed_only=true`) and `GET /categories` |

**Indexes:**
- `ix_products_sku` (UNIQUE) on sku

### sizes

Available print sizes with price adjustments.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Size ID |
| name | VARCHAR | UNIQUE, NOT NULL | Size name (A4, A3, A2, A1) |
| price_delta | NUMERIC(10,2) | NOT NULL | Price adjustment from base |

### frame_options

Frame choices for products.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Frame option ID |
| name | VARCHAR | UNIQUE, NOT NULL | Frame name |
| extra_price | NUMERIC(10,2) | NOT NULL | Additional price |

---

## inventory_schema

### stock

Tracks available and reserved quantities per SKU.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Stock ID |
| sku | VARCHAR | UNIQUE, NOT NULL | SKU reference |
| name | VARCHAR | NOT NULL | Item name |
| available | INTEGER | NOT NULL, DEFAULT 0 | Available quantity |
| reserved | INTEGER | NOT NULL, DEFAULT 0 | Reserved quantity |
| created_at | TIMESTAMP | DEFAULT now() | Record creation |
| updated_at | TIMESTAMP | DEFAULT now() | Last update |

**Indexes:**
- `ix_stock_sku` (UNIQUE) on sku

**Invariant:** `available + reserved = total_stock`

### reservations

Tracks stock reservations with automatic TTL expiry.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Reservation ID |
| order_id | INTEGER | NOT NULL, INDEX | Associated order |
| sku | VARCHAR | NOT NULL | SKU being reserved |
| quantity | INTEGER | NOT NULL | Reserved quantity |
| status | VARCHAR | NOT NULL | active, released, expired, committed |
| created_at | TIMESTAMP | DEFAULT now() | Reservation created |
| expires_at | TIMESTAMP | NOT NULL, INDEX | Expiration time |
| released_at | TIMESTAMP | NULLABLE | When released/expired/committed |

**Indexes:**
- `ix_reservations_expires_at` on expires_at (for expiry worker)
- `ix_reservations_order_id` on order_id

**Status transitions:**
- `active` → `released` (order cancelled)
- `active` → `expired` (TTL exceeded, background worker)
- `active` → `committed` (payment successful)

---

## orders_schema

### orders

Order records with status tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Order ID |
| customer_email | VARCHAR | NOT NULL, INDEX | Customer email |
| status | VARCHAR | NOT NULL, INDEX | Order status |
| total_amount | NUMERIC(10,2) | NOT NULL | Order total |
| checkout_session_id | VARCHAR | NULLABLE | Stripe checkout session |
| payment_intent_id | VARCHAR | NULLABLE | Stripe payment intent (for escrow orders: the contract address) |
| payment_method | VARCHAR | NOT NULL, DEFAULT 'stripe' | `stripe` or `escrow` (`003_escrow.py`; pre-existing rows stay card orders) |
| customer_wallet | VARCHAR(42) | NULLABLE | Customer's Ethereum address (escrow orders only) |
| courier_wallet | VARCHAR(42) | NULLABLE | Courier's payout address, stored on pick-up (CONTRACT B) |
| escrow_contract_address | VARCHAR(42) | NULLABLE | The order's `OrderEscrow` contract |
| escrow_deploy_tx | VARCHAR(66) | NULLABLE | Deploy transaction hash |
| escrow_amount_wei | VARCHAR | NULLABLE | Price in wei as a decimal string — 10^18 does not fit a JS number |
| escrow_status | VARCHAR | NULLABLE, INDEX | Escrow state mirror (see below) |
| created_at | TIMESTAMP | DEFAULT now() | Order created |
| updated_at | TIMESTAMP | DEFAULT now() | Last update |

**Indexes:**
- `ix_orders_customer_email` on customer_email
- `ix_orders_status` on status
- `ix_orders_escrow_status` on escrow_status (the escrow reconciler polls open escrow rows)

**Status values:**
- `created` - Order placed, not yet reserved
- `reserved` - Stock reserved, awaiting payment
- `paid` - Payment successful
- `producing` - In production
- `shipped` - Shipped to customer
- `delivered` - Delivered
- `cancelled` - Cancelled
- `failed` - Failed

**Escrow status values** (`EscrowStatus` in `services/orders/models.py`; the contract enum
plus a local `failed`; `awaiting_payment` and `funded` are the OPEN states in which
`cancel()` refunds):
- `awaiting_payment` - Contract deployed, `pay()` not yet sent
- `funded` - Customer paid the exact price into the contract
- `in_delivery` - Courier bound on chain (`assignCourier()`)
- `released` - `confirmDelivery()` paid courier share + owner remainder
- `cancelled` - `cancel()` closed the contract (refund if it was funded)
- `failed` - Contract vanished from the chain (local state only)

### order_items

Line items for each order.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Item ID |
| order_id | INTEGER | FK, NOT NULL | Parent order |
| sku | VARCHAR | NOT NULL | Product SKU |
| name | VARCHAR | NOT NULL | Product name at time of order |
| quantity | INTEGER | NOT NULL | Quantity ordered |
| unit_price | NUMERIC(10,2) | NOT NULL | Price at time of order |

**Foreign Key:** `order_id` → `orders.id` (CASCADE DELETE)

### outbox_events

Transactional outbox for reliable event delivery.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Event ID |
| event_type | VARCHAR(100) | NOT NULL, INDEX | Event name |
| aggregate_type | VARCHAR(100) | NOT NULL | Entity type (e.g., "order") |
| aggregate_id | VARCHAR(100) | NOT NULL | Entity ID |
| payload | TEXT | NOT NULL | JSON event payload |
| created_at | TIMESTAMP | DEFAULT now() | Event created |
| delivered_at | TIMESTAMP | NULLABLE | When successfully delivered |
| retry_count | INTEGER | NOT NULL, DEFAULT 0 | Delivery attempts |
| retry_after | TIMESTAMP | NULLABLE | Next retry time |
| last_error | TEXT | NULLABLE | Last delivery error |

**Indexes:**
- `ix_outbox_pending` on (delivered_at, retry_after)
- `ix_outbox_event_type` on event_type

---

## production_schema

### jobs

Production jobs created from orders.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Job ID |
| order_id | INTEGER | UNIQUE, NOT NULL | Associated order |
| status | VARCHAR | NOT NULL | Job status |
| items_json | TEXT | NULLABLE | JSON of items to produce |
| created_at | TIMESTAMP | DEFAULT now() | Job created |
| started_at | TIMESTAMP | NULLABLE | Processing started |
| completed_at | TIMESTAMP | NULLABLE | Processing completed |
| processing_time_ms | INTEGER | NULLABLE | Time to process |
| error_message | TEXT | NULLABLE | Error if failed |

**Status values:**
- `queued` - Awaiting processing
- `processing` - Currently being processed
- `completed` - Successfully completed
- `failed` - Processing failed

---

## logistics_schema

### shipments

Shipment tracking records.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Shipment ID |
| order_id | INTEGER | NOT NULL | Associated order |
| status | VARCHAR | NOT NULL | Shipment status |
| tracking | VARCHAR | NULLABLE | Tracking number |
| courier_id | VARCHAR | NULLABLE | Who bound the wallet: the courier's JWT `sub` (their email); NULL when the auto-advance worker bound the default wallet (rendered "system") |
| courier_wallet | VARCHAR(42) | NULLABLE | The wallet sent to orders on pick-up (`003_courier_binding.py`) |
| courier_bound_at | TIMESTAMP | NULLABLE | When the pick-up transition bound the wallet |
| created_at | TIMESTAMP | DEFAULT now() | Shipment created |
| updated_at | TIMESTAMP | DEFAULT now() | Last update |

The three courier columns are written only on the `dispatched -> in_transit` transition
that binds a wallet and are exposed on every shipment response.

**Status values:**
- `preparing` - Being prepared
- `dispatched` - Handed to carrier
- `in_transit` - In transit
- `delivered` - Delivered

---

## notifications_schema

### processed_events

Durable consumer-side idempotency: one row per outbox event whose email was sent successfully.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| event_id | BIGINT | PK, NOT AUTO | Outbox envelope `event_id` |
| event_type | VARCHAR | NOT NULL | Event name (e.g., ORDER_PAID) |
| sent_at | TIMESTAMP | DEFAULT now() | When the send was recorded |

**The primary key is a natural key, not a sequence.** `event_id` is the orders outbox
event's own id, supplied in the delivered envelope rather than generated here — which is
exactly why the column is declared `autoincrement=False`. It is the one primary key in
this document that is not a local sequence.

**Dedup flow:** the handler first selects by `event_id`; a hit is acknowledged as
`already_processed` without sending again, and a miss sends the email and then records the
row with `INSERT ... ON CONFLICT DO NOTHING`. Dedup therefore survives restarts and is
shared across replicas.

---

## designs_schema

Owned by the AI poster studio (`services/designs`, migration `001_initial_schema.py`). Every
table is keyed by the customer's e-mail (the JWT `sub`) — designs never reads `users_schema`.

### generations

One prompt → one asynchronous image job.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Generation ID (also the print SKU: `AI-{id}`) |
| customer_email | VARCHAR | NOT NULL | Owner |
| prompt | TEXT | NOT NULL | What the customer typed |
| effective_prompt | TEXT | NOT NULL | What was sent to the provider — prompt + `Style notes:` when personalised |
| personalise | BOOLEAN | NOT NULL, DEFAULT false | "Personalise" ticked |
| provider | VARCHAR | NOT NULL | `fake` / `openai` / `replicate` at queue time |
| params | JSON | NULLABLE | Provider parameters (size, model, quality, …) |
| status | VARCHAR | NOT NULL | `queued` → `generating` → `ready` \| `failed` |
| failure_reason | TEXT | NULLABLE | Customer-visible reason on `failed` |
| image_key | VARCHAR | NULLABLE | Storage key (32 hex + `.png`); `image_url` is derived, never stored |
| attempts | INTEGER | NOT NULL, DEFAULT 0 | Provider attempts consumed (max `DESIGNS_MAX_ATTEMPTS`) |
| retry_after | TIMESTAMPTZ | NULLABLE | Earliest next claim after a transport failure / open breaker |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Queued at |
| started_at | TIMESTAMPTZ | NULLABLE | Last claim |
| finished_at | TIMESTAMPTZ | NULLABLE | Last attempt's end (stamped after the provider call) |
| purchased_at | TIMESTAMPTZ | NULLABLE | Set once by the ORDER_PAID consumer when a variant was bought |
| catalog_product_sku | VARCHAR | NULLABLE | `AI-{id}` once printed (written last in the print orchestration) |

**Indexes:**
- `ix_generations_customer_created` on (customer_email, created_at) — history and the daily quota count
- `ix_generations_status_retry` on (status, retry_after) — the worker's `FOR UPDATE SKIP LOCKED` claim

### saved_prompts

Prompts the customer keeps for reuse (memory tier 1).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Saved prompt ID |
| customer_email | VARCHAR | NOT NULL, INDEX | Owner |
| title | VARCHAR(120) | NOT NULL | Display title |
| prompt | TEXT | NOT NULL | The prompt |
| created_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Saved at |

**Indexes:**
- `ix_saved_prompts_customer` on customer_email

### style_profiles

One row per customer: the lazily refreshed style summary (memory tier 2).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| customer_email | VARCHAR | PK | Owner (natural key) |
| summary | TEXT | NULLABLE | 1–2 sentences from the summariser |
| prompt_count | INTEGER | NOT NULL, DEFAULT 0 | Prompts fed into the last refresh |
| purchase_count | INTEGER | NOT NULL, DEFAULT 0 | Purchase names fed into the last refresh |
| stale | BOOLEAN | NOT NULL, DEFAULT true | Set by ORDER_PAID; cleared by a successful refresh |
| updated_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Last write |

### purchases

One row per order item from ORDER_PAID — own designs and ordinary posters alike — so the
style profile can name what the customer bought.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | Purchase ID |
| customer_email | VARCHAR | NOT NULL, INDEX | Buyer |
| order_id | INTEGER | NOT NULL | Orders `orders.id` (logical reference) |
| sku | VARCHAR | NOT NULL | Item SKU (`AI-{id}-{size}` for own designs) |
| name | VARCHAR | NOT NULL | Item name from the event payload |
| purchased_at | TIMESTAMPTZ | NOT NULL, DEFAULT now() | Event processing time |

**Constraints / indexes:**
- `uq_purchases_order_sku` UNIQUE on (order_id, sku) — a re-delivered event that slipped past the dedup cannot double-count
- `ix_purchases_customer` on customer_email

### processed_events

Durable consumer-side idempotency for the ORDER_PAID subscription — the notifications precedent.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| event_id | BIGINT | PK, NOT AUTO | Outbox envelope `event_id` (natural key, `autoincrement=False`) |
| event_type | VARCHAR | NOT NULL | Event name (ORDER_PAID) |
| processed_at | TIMESTAMPTZ | DEFAULT now() | When the event was applied |

**Dedup flow:** the handler selects by `event_id` first (`already_processed` on a hit),
otherwise applies the event and records the row with `INSERT ... ON CONFLICT DO NOTHING`
in the same commit; on an `IntegrityError` (purchases left by a crashed earlier delivery)
it rolls back and records the event alone so the outbox stops retrying.

---

## Migrations

Migrations are managed with **Alembic** (per-service):

```bash
# Apply migrations
cd services/<service>
alembic upgrade head

# Create new migration
alembic revision --autogenerate -m "description"

# Rollback
alembic downgrade -1
```

See [MIGRATIONS.md](./MIGRATIONS.md) for detailed migration workflow.

---

## Schema Creation SQL

For reference, here's how schemas are created:

```sql
-- Create schemas (run once on fresh database)
CREATE SCHEMA IF NOT EXISTS users_schema;
CREATE SCHEMA IF NOT EXISTS catalog_schema;
CREATE SCHEMA IF NOT EXISTS inventory_schema;
CREATE SCHEMA IF NOT EXISTS orders_schema;
CREATE SCHEMA IF NOT EXISTS production_schema;
CREATE SCHEMA IF NOT EXISTS logistics_schema;
CREATE SCHEMA IF NOT EXISTS notifications_schema;
CREATE SCHEMA IF NOT EXISTS designs_schema;

-- Tables are created by Alembic migrations
```

---

## Data Relationships (Logical)

While foreign keys are only defined within schemas, these logical relationships exist:

| From | To | Relationship |
|------|----|--------------|
| order_items.sku | products.sku | Order references catalog product |
| order_items.sku | stock.sku | Order references inventory |
| reservations.order_id | orders.id | Reservation for order |
| reservations.sku | stock.sku | Reservation for stock item |
| jobs.order_id | orders.id | Production job for order |
| shipments.order_id | orders.id | Shipment for order |
| products.sku (`AI-{id}`) | generations.id | Printed design → its catalog family (`generations.catalog_product_sku`) |
| stock.sku (`AI-{id}-{size}`) | products.sku | Virtual stock rows for a printed design's variants |
| purchases.order_id | orders.id | Purchase recorded from ORDER_PAID |
| purchases.sku (`AI-{id}-{size}`) | generations.id | A bought design (`generations.purchased_at`) |
