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
**Consumers:** Production Service  
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

---

### ORDER_CANCELLED

**Producer:** Orders Service  
**Consumers:** Production Service  
**Trigger:** Order is cancelled before production starts

**Payload:**
```json
{
  "order_id": 123,
  "previous_status": "reserved",
  "released_stock": true
}
```

**Consumer behavior:**
- If job exists and is `queued`, marks it as `failed` with "Order cancelled"
- If job is already `processing` or `completed`, no action taken

---

## Event Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ORDER LIFECYCLE EVENTS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Orders Service                          Production Service                 │
│   ┌───────────────┐                       ┌───────────────┐                 │
│   │               │                       │               │                 │
│   │  Order Paid   │──── ORDER_PAID ──────▶│  Create Job   │                 │
│   │               │     (outbox)          │   (queued)    │                 │
│   │               │                       │               │                 │
│   │  Order        │──── ORDER_CANCELLED ─▶│  Cancel Job   │                 │
│   │  Cancelled    │     (outbox)          │  (if queued)  │                 │
│   │               │                       │               │                 │
│   └───────────────┘                       └───────────────┘                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
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
EVENT_SUBSCRIBERS = {
    "ORDER_PAID": [
        "http://production:8000/events/order-paid"
    ],
    "ORDER_CANCELLED": [
        "http://production:8000/events/order-cancelled"
    ],
}
```

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

1. **No Dead Letter Queue** - Failed events are abandoned after 5 retries
2. **No Event Idempotency** - Consumers should check for duplicates but don't have a standardized mechanism
3. **Single Consumer Per Event Type** - Fan-out to multiple consumers requires multiple URLs
4. **Polling Latency** - 2-second poll interval adds latency to event delivery
