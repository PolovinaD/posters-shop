# Production Service

Production job processing with simulated CPU-intensive work.

## Purpose

- Process production jobs for paid orders
- Simulate CPU-intensive poster printing
- Coordinate with orders and logistics
- Event consumer for ORDER_PAID events

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- asyncio (job worker)
- httpx (inter-service calls)
- Prometheus metrics

## Database Schema

**Schema:** `production_schema`

### jobs
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| order_id | INTEGER | Associated order (unique) |
| status | VARCHAR | queued, processing, completed, failed |
| items_json | TEXT | JSON of items to produce |
| created_at | TIMESTAMP | Job created |
| started_at | TIMESTAMP | Processing started |
| completed_at | TIMESTAMP | Processing finished |
| processing_time_ms | INTEGER | Processing duration |
| error_message | TEXT | Error if failed |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /jobs | Create job | Internal |
| GET | /jobs | List jobs | Admin |
| GET | /jobs/{id} | Get job | Admin |
| GET | /jobs/order/{order_id} | Get job by order | Admin |
| POST | /jobs/{id}/retry | Retry failed job | Admin |
| GET | /jobs/stats/summary | Job statistics | Admin |
| POST | /events/order-paid | Handle ORDER_PAID | Internal |
| POST | /events/order-cancelled | Handle ORDER_CANCELLED | Internal |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| ORDERS_SERVICE_URL | Orders service | `http://orders:8000` |
| LOGISTICS_SERVICE_URL | Logistics service | `http://logistics:8000` |

## Local Development

```bash
cd services/production
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8005
```

## Job Lifecycle

```
ORDER_PAID event
       │
       ▼
    queued ─────────────────────────────────┐
       │                                    │
       ▼                                    │
  processing (notify orders: producing)     │
       │                                    │
       ├────success────▶ completed          │
       │                    │               │
       │                    ▼               │
       │              notify orders: shipped│
       │              create shipment       │
       │                                    │
       └────failure────▶ failed ◀───────────┘
                              (order cancelled)
```

## Events Consumed

| Event | Handler | Action |
|-------|---------|--------|
| ORDER_PAID | `/events/order-paid` | Create job (idempotent) |
| ORDER_CANCELLED | `/events/order-cancelled` | Cancel queued job |

## CPU Simulation

The `simulate_production_work()` function:
- Parses order items
- Scales work by total quantity
- Performs CPU-intensive calculations
- Returns processing time in milliseconds

Used for HPA (Horizontal Pod Autoscaler) demonstration.

## Background Worker

The `job_worker` runs continuously:
1. Polls for queued jobs (FIFO)
2. Uses `SELECT ... FOR UPDATE SKIP LOCKED` for concurrency
3. Processes one job at a time
4. Updates order status via HTTP calls
5. Creates shipment on completion

## Metrics

- `production_jobs_created_total`: Jobs created
- `production_jobs_completed_total{status}`: Completed/failed jobs
- `production_jobs_in_queue`: Current queue length
- `production_job_processing_time_seconds`: Processing time histogram

## Dependencies

- **Orders Service**: Status updates (produce, ship)
- **Logistics Service**: Shipment creation
