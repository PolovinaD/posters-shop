# Payments Service

Real Stripe Hosted Checkout — a thin wrapper that creates sessions and hands back
Stripe's hosted checkout URL — plus an Ethereum escrow provider for paying with Ether.

## Purpose

- Create Stripe Hosted Checkout sessions via `stripe.checkout.Session.create()`
- Return the Stripe-hosted `checkout_url` to the caller (the orders service)
- Read session state back from Stripe on demand
- Drive one `OrderEscrow` contract per order on an Ethereum JSON-RPC node (Ganache in
  every environment so far) through web3, from a shop-owned key (`escrow.py`,
  `EscrowProvider` — the same provider shape as notifications' `EmailProvider`)
- Hold no state of its own — no database, no local session store; escrow state lives on
  chain and on the orders row
- **Non-goal:** this service does **not** deliver webhooks. Stripe sends
  `checkout.session.completed` straight to the orders service.

## Tech Stack

- FastAPI
- Stripe Python SDK — `stripe==15.0.1`
- web3 — `web3>=7.13,<8` (with `eth-account` for the owner key and the Ganache HD wallet)
- Solidity 0.8.28 — `contracts/OrderEscrow.sol`, compiled into the committed
  `contracts/OrderEscrow.json` by `make contract-compile` (`ethereum/solc:0.8.28` in docker)
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
| GET | /v1/escrow/config | `{rpc_url, wei_per_usd, courier_share_bps, enabled, chain_id, owner_address}`; never 503s — `enabled: false` when there is no owner key or the chain is down | - |
| GET | /v1/escrow/demo-accounts | Ganache's ten deterministic accounts with keys; 404 unless `ESCROW_EXPOSE_DEMO_ACCOUNTS` **and** the node is Ganache | - |
| POST | /v1/escrow | Deploy an `OrderEscrow` for `{order_id, customer_address, amount_usd}` from the owner key | service or owner |
| GET | /v1/escrow/{address} | Live chain state `{state, owner, customer, courier, price_wei, balance_wei}` | service or owner |
| GET | /v1/escrow/{address}/invoice | The unsigned `pay()` tx the customer's wallet signs `{to, value, data, chain_id}` | service or owner |
| POST | /v1/escrow/{address}/courier | `assignCourier()` with `{courier_address}` | service or owner |
| POST | /v1/escrow/{address}/release | `confirmDelivery()` — courier share + owner remainder | service or owner |
| POST | /v1/escrow/{address}/cancel | `cancel()` — refunds the customer if funded | service or owner |
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
| ESCROW_RPC_URL | Ethereum JSON-RPC endpoint this service talks to | `http://ganache:8545` |
| ESCROW_PUBLIC_RPC_URL | RPC URL handed to the browser in `/v1/escrow/config` (the nginx `/rpc` proxy) | `/rpc` |
| ESCROW_OWNER_PRIVATE_KEY | Shop-owned key that deploys every contract and sends everything but `pay()` | None — escrow disabled without it |
| WEI_PER_USD | Fixed conversion rate, wei per dollar (0.001 ETH); no oracle | `1000000000000000` |
| ESCROW_COURIER_SHARE_BPS | Courier's share on `confirmDelivery()`, basis points (20 %) | `2000` |
| ESCROW_OWNER_MIN_BALANCE_ETH | On Ganache: top the owner up from account[0] below this balance | `10` |
| ESCROW_OWNER_TOPUP_ETH | Size of that startup top-up | `100` |
| ESCROW_EXPOSE_DEMO_ACCOUNTS | Serve the demo accounts at `/v1/escrow/demo-accounts` (Ganache only) | `true` |
| ESCROW_RPC_TIMEOUT | Seconds per JSON-RPC call | `5` |

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

## Escrow Flow

```
0. Startup: init_provider() never raises — no ESCROW_OWNER_PRIVATE_KEY -> "Escrow disabled",
   chain unreachable -> warning, Stripe keeps working. On Ganache the owner is topped up
   from the node's unlocked account[0] when below ESCROW_OWNER_MIN_BALANCE_ETH
   ↓
1. Orders: POST /v1/escrow {order_id, customer_address, amount_usd}
   -> one OrderEscrow deployed from the owner key; amount = amount_usd * WEI_PER_USD
   ↓
2. Orders: GET /v1/escrow/{address}/invoice -> the unsigned pay() tx
   ↓
3. Customer signs pay() in the browser (ethers) and sends it through /rpc — the ONE
   transaction the customer ever signs; the contract requires the exact price
   ↓
4. Orders: GET /v1/escrow/{address} on verify -> "funded" -> orders runs mark_order_paid
   ↓
5. Logistics pick-up -> orders: POST /v1/escrow/{address}/courier {courier_address}
   -> assignCourier() -> "in_delivery"
   ↓
6. Customer confirms delivery -> orders: POST /v1/escrow/{address}/release
   -> confirmDelivery() pays ESCROW_COURIER_SHARE_BPS to the courier, the rest to the owner
```

`POST /v1/escrow/{address}/cancel` runs `cancel()` while the contract is
`awaiting_payment` or `funded` (refunding the customer in the second case); orders calls
it on cancel and on reservation expiry.

Contract failures map onto HTTP status codes (`_escrow_call`, `main.py`):

| Exception | Response |
|-----------|----------|
| `EscrowRevert` | **409** with the bare `require` reason (`"Only owner."`, `"Transfer not complete."`, `"Delivery not complete."`, `"Cannot cancel."`, ...; the Ganache prefix is stripped) |
| `EscrowNotFound` | **404** — no contract code at that address |
| `EscrowUnavailable` | **503** `"Escrow unavailable: ..."` — chain down or no owner key (`/config` answers `enabled: false` instead) |

`{address}` is `Path(pattern="^0x[0-9a-fA-F]{40}$")`; the handlers are plain `def`
because web3 is synchronous and runs in FastAPI's threadpool.

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
- **Ganache** (`ESCROW_RPC_URL`): the Ethereum node the escrow provider signs against;
  docker-compose starts this service with `depends_on: ganache: service_healthy`
- **Orders Service**: the caller, and the destination Stripe posts webhooks to — this
  service never calls orders
