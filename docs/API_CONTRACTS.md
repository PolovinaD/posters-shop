# Inter-Service API Contracts

This document defines the APIs used for service-to-service communication.

---

## Overview

| Caller | Callee | Purpose | Protocol |
|--------|--------|---------|----------|
| Orders | Inventory | Stock reservation/commit | Sync HTTP |
| Orders | Payments | Checkout sessions | Sync HTTP |
| Orders (Outbox) | Production | Order events (ORDER_PAID, ORDER_CANCELLED) | Async HTTP |
| Orders (Outbox) | Notifications | Order events (all four types) — transactional email | Async HTTP |
| Production | Orders | Status updates | Sync HTTP |
| Production | Logistics | Create shipment | Sync HTTP |
| Logistics | Orders | Delivery notification | Sync HTTP |
| Catalog | Inventory | Stock check | Sync HTTP |
| Payments | Orders | Webhook | Async HTTP |

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
| `200 {"status": "skipped", "reason": "no_customer_email"}` | Payload carried no address | **Deliberately 200, not 4xx.** Retrying cannot make a missing address appear, so a non-2xx here would burn all five retries and then abandon the event for no reason |
| `503` | The email provider raised on send | **Deliberately retryable.** A transient SES failure should be retried with backoff, so the event is left undelivered and the worker tries again |

The distinction reduces to: **200 means "do not retry, there is nothing more to do";
503 means "retry, this might succeed later."** The service returns `200` for the skip
case precisely so that a permanently unfixable input does not consume the retry budget.

### Idempotency

Guarded by an in-memory set of processed `event_id` values
(`services/notifications/main.py`). This is per-replica and does not survive a restart,
so a duplicate email is possible after a pod restart or with `replicaCount > 1`.

### Health & Metrics

```http
GET /healthz    # liveness
GET /readyz     # readiness — always ready, no DB to check
GET /metrics    # Prometheus
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

**Called by:** Payments Service  
**When:** Customer completes payment

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
| Event delivery | 5s connect, 10s total | 5x with exponential backoff |
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
