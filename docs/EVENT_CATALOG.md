# Event Catalog

This document catalogs all events in the shop-platform event-driven architecture.

## Overview

Events are delivered using the **Transactional Outbox Pattern**:
1. Events are written to `outbox_events` table in the same transaction as business data
2. Background worker polls outbox and delivers via HTTP POST
3. At-least-once delivery with exponential backoff retry

**Delivery guarantees:**
- At-least-once delivery (consumers must be idempotent)
- Max 5 retries with delays: 5s, 15s, 1m, 5m, 15m
- Events exceeding retries are abandoned (no DLQ currently)

---

## Events

### ORDER_PAID

**Producer:** Orders Service  
**Consumers:** Production Service, Notifications Service  
**Trigger:** Order status transitions to `paid` after successful payment

**Payload:**
```json
{
  "order_id": 123,
  "customer_email": "customer@example.com",
  "total_amount": "99.99",
  "items": [
    {
      "sku": "POSTER-SUNSET-A3",
      "name": "Golden Sunset",
      "quantity": 2
    }
  ]
}
```

**Consumer behavior:**
- Production service creates a `Job` in `queued` status
- Idempotency: Checks if job already exists for order_id before creating
- Notifications service sends the order-confirmation email
- Idempotency: In-memory `event_id` set (per replica, non-durable)

---

### ORDER_CANCELLED

**Producer:** Orders Service  
**Consumers:** Production Service, Notifications Service  
**Trigger:** Order is cancelled — either by the customer, or by the Stripe
`checkout.session.expired` webhook path

**Payload:**
```json
{
  "order_id": 123,
  "customer_email": "customer@example.com",
  "previous_status": "reserved",
  "released_stock": true,
  "reason": "cancelled by customer"
}
```

`customer_email` and `reason` are required by the notifications consumer. The
`checkout.session.expired` path previously emitted no event at all; it now emits
`ORDER_CANCELLED` with the customer's address so the cancellation email is sent.

**Consumer behavior:**
- If job exists and is `queued`, marks it as `failed` with "Order cancelled"
- If job is already `processing` or `completed`, no action taken
- Notifications service sends the cancellation email. The wording is conditional
  on `released_stock` and `previous_status`, so it never claims stock was
  released when it was not, and never asserts a payment outcome for an order
  that was already paid (see `docs/KNOWN_LIMITATIONS.md`)

---

### ORDER_SHIPPED

**Producer:** Orders Service  
**Consumers:** Notifications Service  
**Trigger:** `POST /orders/{id}/ship` — emitted in the same transaction as the
status change to `shipped`

**Payload:**
```json
{
  "order_id": 123,
  "customer_email": "customer@example.com",
  "items": [
    {
      "sku": "POSTER-SUNSET-A3",
      "name": "Golden Sunset",
      "quantity": 2
    }
  ]
}
```

**Consumer behavior:**
- Notifications service sends the shipment-notification email
- No production-side consumer

---

### ORDER_DELIVERED

**Producer:** Orders Service  
**Consumers:** Notifications Service  
**Trigger:** `POST /orders/{id}/deliver` — emitted in the same transaction as the
status change to `delivered`

**Payload:**
```json
{
  "order_id": 123,
  "customer_email": "customer@example.com",
  "items": [
    {
      "sku": "POSTER-SUNSET-A3",
      "name": "Golden Sunset",
      "quantity": 2
    }
  ]
}
```

**Consumer behavior:**
- Notifications service sends the delivery-confirmation email
- No production-side consumer

---

## Event Flow Diagram

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              ORDER LIFECYCLE EVENTS                                     │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│   Orders Service                    Production Service          Notifications Service   │
│   ┌───────────────┐                 ┌───────────────┐           ┌──────────────────┐   │
│   │               │                 │               │           │                  │   │
│   │  Order Paid   │─ ORDER_PAID ───▶│  Create Job   │           │                  │   │
│   │               │   (outbox)      │   (queued)    │           │                  │   │
│   │               │   └─────────────────────────────────────── ▶│  Confirmation    │   │
│   │               │                 │               │           │  email           │   │
│   │               │                 │               │           │                  │   │
│   │  Order        │─ ORDER_CANCELLED│  Cancel Job   │           │                  │   │
│   │  Cancelled    │   (outbox)  ───▶│  (if queued)  │           │                  │   │
│   │               │   └─────────────────────────────────────── ▶│  Cancellation    │   │
│   │               │                 │               │           │  email           │   │
│   │               │                 │               │           │                  │   │
│   │  Order        │─ ORDER_SHIPPED ─────────────────────────── ▶│  Shipped email   │   │
│   │  Shipped      │   (outbox)      │               │           │                  │   │
│   │               │                 │               │           │                  │   │
│   │  Order        │─ ORDER_DELIVERED────────────────────────── ▶│  Delivered email │   │
│   │  Delivered    │   (outbox)      │               │           │                  │   │
│   └───────────────┘                 └───────────────┘           └──────────────────┘   │
│                                                                                         │
│   ORDER_PAID and ORDER_CANCELLED fan out to BOTH consumers (publish-subscribe).          │
│   ORDER_SHIPPED and ORDER_DELIVERED have a single consumer.                             │
│                                                                                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Outbox Table Schema

**Location:** `orders_schema.outbox_events`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| event_type | VARCHAR(100) | Event name (e.g., ORDER_PAID) |
| aggregate_type | VARCHAR(100) | Entity type (e.g., "order") |
| aggregate_id | VARCHAR(100) | Entity ID (e.g., order_id) |
| payload | TEXT | JSON payload |
| created_at | TIMESTAMP | Event creation time |
| delivered_at | TIMESTAMP | Successful delivery time (NULL if pending) |
| retry_count | INTEGER | Number of delivery attempts |
| retry_after | TIMESTAMP | Next retry time (for failed deliveries) |
| last_error | TEXT | Last delivery error message |

**Indexes:**
- `ix_outbox_pending` on (delivered_at, retry_after) - for polling
- `ix_outbox_event_type` on (event_type) - for filtering

---

## Event Envelope

Events are delivered with this envelope structure:

```json
{
  "event_id": 42,
  "event_type": "ORDER_PAID",
  "aggregate_type": "order",
  "aggregate_id": "123",
  "payload": { ... },
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

## Subscriber Configuration

Subscribers are configured in `services/orders/outbox.py`:

```python
NOTIFICATIONS_SERVICE_URL = os.getenv("NOTIFICATIONS_SERVICE_URL", "http://notifications:8000")

# ORDER_PAID / ORDER_CANCELLED fan out to BOTH production and notifications;
# ORDER_SHIPPED / ORDER_DELIVERED go to notifications only.
EVENT_SUBSCRIBERS = {
    "ORDER_PAID": [
        os.getenv("PRODUCTION_SERVICE_URL", "http://production:8000") + "/events/order-paid",
        NOTIFICATIONS_SERVICE_URL + "/events/order-paid",
    ],
    "ORDER_CANCELLED": [
        os.getenv("PRODUCTION_SERVICE_URL", "http://production:8000") + "/events/order-cancelled",
        NOTIFICATIONS_SERVICE_URL + "/events/order-cancelled",
    ],
    "ORDER_SHIPPED": [
        NOTIFICATIONS_SERVICE_URL + "/events/order-shipped",
    ],
    "ORDER_DELIVERED": [
        NOTIFICATIONS_SERVICE_URL + "/events/order-delivered",
    ],
}
```

Four event types across six subscriber URLs. Subscriber base URLs are read from
environment variables so the same map works in docker-compose and in Kubernetes.

---

## Monitoring

**Outbox stats endpoint:** `GET /orders/outbox/stats`

Returns:
- `pending_count`: Events awaiting delivery
- `failed_count`: Events that exceeded max retries
- `recent_events`: Last 10 events with status

**Prometheus metrics:**
- Events are logged with structured JSON for Loki queries

---

## Adding New Events

1. Define event type in `EVENT_SUBSCRIBERS` dict
2. Add subscriber URL(s)
3. Call `emit_event()` within the same transaction as business logic:

```python
emit_event(
    db=db,
    event_type="NEW_EVENT",
    aggregate_type="entity_type",
    aggregate_id=str(entity_id),
    payload={"key": "value"}
)
```

4. Implement consumer endpoint that:
   - Accepts the event envelope
   - Checks for idempotency (has this event_id been processed?)
   - Processes the event
   - Returns 200 on success

---

## Known Limitations

1. **No Dead Letter Queue** - Failed events are abandoned after 5 retries. This
   matters more now that email delivery rides the outbox: a subscriber outage
   longer than the retry window silently drops customer email.
2. **No Event Idempotency** - Consumers should check for duplicates but don't have a
   standardized mechanism. Production uses a database lookup; notifications uses an
   in-memory set that does not survive a pod restart.
3. **Retry Is Per-Event, Not Per-Subscriber** - Fan-out to multiple consumers is in
   use (`ORDER_PAID` and `ORDER_CANCELLED` each go to two services), but the retry
   unit is the whole event, not the individual subscriber. If any one subscriber
   fails, the entire event is retried and **re-delivered to subscribers that had
   already succeeded**. Consumers must therefore be idempotent even when they are
   themselves healthy.
4. **Polling Latency** - 2-second poll interval adds latency to event delivery
