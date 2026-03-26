# Logistics Service

Shipment tracking and delivery management.

## Purpose

- Create shipments for completed orders
- Track shipment status
- Notify orders service on delivery
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
| created_at | TIMESTAMP | Shipment created |
| updated_at | TIMESTAMP | Last update |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /ship | Create shipment | Internal |
| GET | /shipments | List shipments | Admin |
| GET | /shipments/{id} | Get shipment | - |
| GET | /shipments/order/{order_id} | Get by order | - |
| PUT | /shipments/{id}/status | Update status | Courier/Admin |
| POST | /webhooks/delivery-update | External webhook | - |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| ORDERS_SERVICE_URL | Orders service | `http://orders:8000` |
| JWT_SECRET | For courier auth | `change_me` |

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

## Events

None - this service doesn't produce or consume outbox events (sync API only).

## Dependencies

- **Orders Service**: Delivery notification
