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
| payment_intent_id | VARCHAR | NULLABLE | Stripe payment intent |
| created_at | TIMESTAMP | DEFAULT now() | Order created |
| updated_at | TIMESTAMP | DEFAULT now() | Last update |

**Indexes:**
- `ix_orders_customer_email` on customer_email
- `ix_orders_status` on status

**Status values:**
- `created` - Order placed, not yet reserved
- `reserved` - Stock reserved, awaiting payment
- `paid` - Payment successful
- `producing` - In production
- `shipped` - Shipped to customer
- `delivered` - Delivered
- `cancelled` - Cancelled
- `failed` - Failed

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
| created_at | TIMESTAMP | DEFAULT now() | Shipment created |
| updated_at | TIMESTAMP | DEFAULT now() | Last update |

**Status values:**
- `preparing` - Being prepared
- `dispatched` - Handed to carrier
- `in_transit` - In transit
- `delivered` - Delivered

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
