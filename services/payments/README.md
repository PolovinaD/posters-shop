# Payments Service

Mock Stripe payment service for testing.

## Purpose

- Simulate Stripe Checkout API
- Generate checkout sessions
- Send signed webhooks to orders service
- Provide test payment flow

## Tech Stack

- FastAPI
- httpx (webhook delivery)
- In-memory session storage (no database)

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /v1/checkout/sessions | Create session | - |
| GET | /v1/checkout/sessions | List sessions | - |
| GET | /v1/checkout/sessions/{id} | Get session | - |
| POST | /v1/checkout/sessions/{id}/complete | Simulate payment | - |
| POST | /v1/checkout/sessions/{id}/expire | Expire session | - |
| GET | /checkout/{id} | Mock checkout page | - |
| GET | /webhook-secret | Get test secret | - |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| STRIPE_WEBHOOK_SECRET | Webhook signing key | `whsec_test_secret_key_12345` |
| ORDERS_WEBHOOK_URL | Orders webhook endpoint | `http://orders:8000/webhooks/stripe` |

## Local Development

```bash
cd services/payments
pip install -r requirements.txt
uvicorn main:app --reload --port 8007
```

**Note:** No database required - sessions stored in memory.

## Checkout Flow

```
1. Orders Service: POST /v1/checkout/sessions
   ↓
2. Customer redirected to checkout_url
   ↓
3. Customer "pays": POST /v1/checkout/sessions/{id}/complete
   ↓
4. Webhook sent to orders: checkout.session.completed
   ↓
5. Orders processes payment
```

## Session States

| Status | Description |
|--------|-------------|
| open | Awaiting payment |
| complete | Payment successful |
| expired | Session timed out |

## Webhook Signature

Mimics Stripe's signature format:

```
Stripe-Signature: t=1234567890,v1=abc123...
```

Signature = HMAC-SHA256(`{timestamp}.{payload}`, webhook_secret)

## Test Cards

| Number | Result |
|--------|--------|
| 4242424242424242 | Success |
| 4000000000000002 | Decline |

## Webhook Events

### checkout.session.completed
```json
{
  "id": "evt_test_123",
  "type": "checkout.session.completed",
  "data": {
    "object": {
      "id": "cs_test_abc",
      "payment_status": "paid",
      "payment_intent": "pi_test_xyz",
      "amount_total": 4998,
      "metadata": {
        "order_id": "123"
      }
    }
  }
}
```

### checkout.session.expired
```json
{
  "id": "evt_test_456",
  "type": "checkout.session.expired",
  "data": {
    "object": {
      "id": "cs_test_abc",
      "payment_status": "unpaid"
    }
  }
}
```

## Production Migration

To use real Stripe:
1. Replace this service with actual Stripe SDK calls
2. Configure real webhook endpoint in Stripe dashboard
3. Use production webhook secret
4. Remove mock checkout page

## Dependencies

- **Orders Service**: Webhook consumer
