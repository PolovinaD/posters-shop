# Payments Service

Real Stripe Hosted Checkout — a thin wrapper that creates sessions and hands back
Stripe's hosted checkout URL.

## Purpose

- Create Stripe Hosted Checkout sessions via `stripe.checkout.Session.create()`
- Return the Stripe-hosted `checkout_url` to the caller (the orders service)
- Read session state back from Stripe on demand
- Hold no state of its own — no database, no local session store
- **Non-goal:** this service does **not** deliver webhooks. Stripe sends
  `checkout.session.completed` straight to the orders service.

## Tech Stack

- FastAPI
- Stripe Python SDK — `stripe==15.0.1`
- prometheus-client (request metrics)
- No database and no local session store — session state lives at Stripe

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /v1/checkout/sessions | Create a Stripe Hosted Checkout session | - |
| GET | /v1/checkout/sessions | Always returns `[]` — sessions live at Stripe | - |
| GET | /v1/checkout/sessions/{session_id} | Retrieve a session from Stripe | - |
| POST | /v1/checkout/sessions/{session_id}/complete | **Dev/test only** — returns `dev_only`, does not pay | - |
| POST | /v1/checkout/sessions/{session_id}/expire | **Dev/test only** — returns `dev_only` | - |
| GET | /healthz | Liveness probe | - |
| GET | /readyz | Readiness probe (no DB to check) | - |
| GET | /metrics | Prometheus metrics | - |

Create maps Stripe's `session.url` onto the `checkout_url` field, preserving the API
surface the orders service consumes (`main.py:156`).

Stripe failures map onto HTTP status codes:

| Endpoint | Stripe exception | Response |
|----------|------------------|----------|
| create | `AuthenticationError` | 503 |
| create | `StripeError` | 502 |
| retrieve | `InvalidRequestError` | 404 |
| retrieve | `StripeError` | 502 |

The list endpoint is kept only for API compatibility — real listing would require a
Stripe API call, so it returns an empty list. The two dev/test endpoints log a warning
and no longer simulate anything: they return `dev_only` and change no state. Stripe
expires sessions itself after 24 hours.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| STRIPE_SECRET_KEY | Stripe API key (test or live). No default — the SDK raises `AuthenticationError` on the first API call if it is missing or invalid | None — required |
| STRIPE_WEBHOOK_SECRET | Stripe webhook signing secret. Read here, but the signature check that consumes it lives in orders (`services/orders/stripe_webhook.py`), because Stripe posts to orders | `whsec_test_secret_key_12345` |
| FRONTEND_URL | Base URL used to build `success_url` / `cancel_url` | `http://localhost:3000` |
| ROOT_PATH | ASGI root path prefix | `""` |
| CORS_ORIGINS | Comma-separated allowed origins | `http://localhost:3000` |

## Local Development

```bash
cd services/payments
pip install -r requirements.txt
uvicorn main:app --reload --port 8007
```

**Note:** No database is required. Session creation calls Stripe for real, so a
test-mode API key (first row above) must be set or the call fails with `503`.

## Checkout Flow

```
1. Orders: POST /v1/checkout/sessions
   ↓
2. Payments calls Stripe and returns the hosted checkout_url
   ↓
3. Customer is redirected to Stripe's hosted payment page
   ↓
4. Stripe charges the card
   ↓
5. Stripe delivers checkout.session.completed to ORDERS, not to this service
   ↓
6. Orders verifies the signature and marks the order paid
```

The webhook endpoint registered in the Stripe Dashboard therefore points at orders:
`https://<ALB>/api/orders/webhooks/stripe`. The `/api/orders` prefix is added by
nginx/ALB routing — the route declared in orders is `/webhooks/stripe`.

## Session States

| Status | Description |
|--------|-------------|
| open | Awaiting payment |
| complete | Payment successful |
| expired | Session timed out |

## Test Cards

Stripe's test-mode cards, entered on the hosted page when the service runs with a
test-mode key:

| Number | Result |
|--------|--------|
| 4242424242424242 | Success |
| 4000000000000002 | Decline |

## Dependencies

- **Stripe API**: upstream — session creation and retrieval
- **Orders Service**: the caller, and the destination Stripe posts webhooks to — this
  service never calls orders
</content>
</invoke>
