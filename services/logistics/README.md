# Logistics Service

Shipment tracking and delivery management.

## Purpose

- Create shipments for completed orders
- Track shipment status
- Notify orders service on delivery
- Send the courier's payout wallet to orders on pick-up (escrow CONTRACT B) and record who bound it
- Support external delivery webhooks

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- httpx (inter-service calls)
- BackgroundTasks (async notifications)

## Database Schema

**Schema:** `logistics_schema`

### shipments
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| order_id | INTEGER | Associated order |
| status | VARCHAR | preparing, dispatched, in_transit, delivered |
| tracking | VARCHAR | Tracking number |
| courier_id | VARCHAR | Who bound the wallet: the courier's JWT `sub` (their email); NULL when the auto-advance worker bound the default wallet — shown as "system" (`003_courier_binding.py`) |
| courier_wallet | VARCHAR(42) | The wallet sent to orders on pick-up |
| courier_bound_at | TIMESTAMP | When the pick-up transition bound it |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /ship | Create shipment | Internal |
| GET | /shipments | List shipments | Courier/Admin |
| GET | /shipments/{id} | Get shipment | Courier/Admin |
| GET | /shipments/order/{order_id} | Get by order | Courier/Admin |
| PUT | /shipments/{id}/status | Update status; optional body `courier_wallet` (`0x` + 40 hex). On `dispatched -> in_transit` it (else `LOGISTICS_DEFAULT_COURIER_WALLET`) is sent to orders `POST /internal/orders/{id}/courier` as a background task and the binding is recorded on the shipment | Courier/Admin |
| POST | /webhooks/delivery-update | External webhook | - |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| ORDERS_SERVICE_URL | Orders service | `http://orders:8000` |
| JWT_SECRET | For courier auth | `change_me` |
| LOGISTICS_DEFAULT_COURIER_WALLET | Wallet bound on pick-up when the status update carries none (the unattended worker's courier) | None — unset binds no wallet; docker-compose and the chart set Ganache account[2] `0x22d491bde2303f2f43325b2108d26f1eaba1e32b` |

## Local Development

```bash
cd services/logistics
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8006
```

## Shipment Lifecycle

```
POST /ship
    │
    ▼
dispatched ──▶ in_transit ──▶ delivered
                                  │
                                  ▼
                         notify orders (async)
```

## Status Transitions

| From | To | Valid |
|------|----|-------|
| dispatched | in_transit | ✓ |
| dispatched | delivered | ✓ |
| in_transit | delivered | ✓ |
| delivered | * | ✗ (terminal) |

## Tracking Number Format

Auto-generated: `TRK-{order_id:06d}`

Example: `TRK-000123` for order 123

## External Webhook

For integration with delivery providers (DHL, FedEx, etc.):

```http
POST /webhooks/delivery-update
{
  "tracking_number": "TRK-000123",
  "status": "delivered"
}
```

Status mapping:
- `picked_up` → `dispatched`
- `in_transit` → `in_transit`
- `out_for_delivery` → `in_transit`
- `delivered` → `delivered`

## Auto-Notification

When status changes to `delivered`, automatically notifies orders service to update order status.

## Courier Wallet Binding

CONTRACT B: on the pick-up transition (`dispatched -> in_transit`) the courier's Ethereum
wallet — the `courier_wallet` in the status body, else `LOGISTICS_DEFAULT_COURIER_WALLET`,
else nothing — is POSTed to orders `/internal/orders/{order_id}/courier` with a service
token (`orders_client.notify_courier_assigned`, fire-and-forget; orders always answers 200
and its reconciler retries anything it could not bind on chain). The same transition
records `courier_id` (`courier_id_from_claims`: the JWT `sub`, `None` for `service:` and
worker callers), `courier_wallet` and `courier_bound_at` on the shipment, and every
shipment response carries the three fields (`shipment_to_dict`). The rule that decides
whether a transition binds is `worker_rules.courier_binding_wallet`.

## Events

None - this service doesn't produce or consume outbox events (sync API only).

## Dependencies

- **Orders Service**: Delivery notification and the courier wallet binding on pick-up
