# Inter-Service API Contracts

This document defines the APIs used for service-to-service communication.

---

## Overview

| Caller | Callee | Purpose | Protocol |
|--------|--------|---------|----------|
| Orders | Inventory | Stock reservation/commit | Sync HTTP |
| Orders | Payments | Checkout sessions | Sync HTTP |
| Orders (Outbox) | Production | Order events | Async HTTP |
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
    "previous_status": "reserved",
    "released_stock": true
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
