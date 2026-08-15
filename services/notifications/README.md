# Notifications Service

Transactional email on order-lifecycle events.

## Purpose

- Subscribe to the orders outbox and send email for order-lifecycle events
- Render plain-text subject and body per event type
- Abstract the email transport so local development needs no AWS credentials
- Expose delivery counters for Prometheus

## Tech Stack

- FastAPI
- boto3 (AWS SES transport)
- prometheus-client (delivery metrics)
- SQLAlchemy + Alembic — owns `notifications_schema` with a `processed_events`
  idempotency table, migrated like every other DB-backed service

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /events/order-paid | Send order-confirmation email | - |
| POST | /events/order-shipped | Send shipment-notification email | - |
| POST | /events/order-delivered | Send delivery-confirmation email | - |
| POST | /events/order-cancelled | Send cancellation email | - |
| GET | /healthz | Liveness probe | - |
| GET | /readyz | Readiness probe (checks DB connectivity) | - |
| GET | /metrics | Prometheus metrics | - |

The `/events/*` endpoints are called by the orders outbox worker over cluster-internal
DNS. They are not exposed through the ALB (`ingress.enabled: false`).

### Response Contract

The status code is load-bearing, because the outbox worker retries on failure:

| Response | Meaning | Outbox behaviour |
|----------|---------|------------------|
| `200 {"status": "sent"}` | Email handed to the provider | Marked delivered |
| `200 {"status": "already_processed"}` | Duplicate `event_id` | Marked delivered |
| `200 {"status": "skipped", "reason": "no_customer_email"}` | Nothing to send | Marked delivered — **deliberately 200**, since retrying cannot make an absent address appear |
| `503` | Provider raised on send | **Retried** with exponential backoff |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| EMAIL_PROVIDER | Transport selector: `ses` for AWS SES, anything else for the logging provider | `logging` |
| EMAIL_FROM | Sender address — must be a verified SES identity when using SES | `no-reply@postershop.example` |
| SES_REGION | Region holding the verified sender identity | `eu-central-1` |
| SERVICE_NAME | Service name used in logs and metrics labels | `notifications` |
| LOG_LEVEL | Logging level | `INFO` |
| CORS_ORIGINS | Comma-separated allowed origins | `http://localhost:3000` |

`SES_REGION` is intentionally independent of the cluster region (`eu-north-1`). SES is
regional, and a verified sender identity does not have to live in the region of the
workload that calls it.

## Local Development

```bash
cd services/notifications
pip install -r requirements.txt
uvicorn main:app --reload --port 8009
```

**Note:** The service is DB-backed. It owns `notifications_schema` (a single
`processed_events` idempotency table) and runs its Alembic migration under
docker-compose via the `notifications-migrate` service, exactly like the other
DB-backed services. `make dev` still works credential-free: `EMAIL_PROVIDER`
defaults to `logging`, so no AWS credentials are needed.

The default logging provider needs no AWS credentials, so the full event flow is
demoable locally:

```bash
curl -X POST http://localhost:8009/events/order-paid \
  -H 'Content-Type: application/json' \
  -d '{
    "event_id": 1,
    "event_type": "ORDER_PAID",
    "aggregate_type": "order",
    "aggregate_id": "123",
    "payload": {
      "order_id": 123,
      "customer_email": "customer@example.com",
      "total_amount": "99.99"
    }
  }'
```

The rendered email appears in the service log. Re-sending the same `event_id` returns
`already_processed`.

## Email Providers

Transport is selected at startup by `EMAIL_PROVIDER` (`providers.py`, `get_provider()`).

### LoggingProvider (default)

Renders the email into the structured log instead of sending it. Requires no AWS
credentials, which makes it the right choice for docker-compose and for demos.

### SesProvider

Sends through AWS SES using boto3.

Credentials are **never stored**. In production the pod assumes an IAM role granting
`ses:SendEmail` through IRSA (*IAM Roles for Service Accounts*), bound to its
ServiceAccount; boto3 picks the role up automatically. There is no access key in the
image, in a Kubernetes Secret, or in AWS Secrets Manager.

Setup is documented in [deploy/README.md](../../deploy/README.md) under
"Email Delivery Setup (SES via IRSA)".

## Events Consumed

| Event | Emitted by | Email sent |
|-------|-----------|------------|
| ORDER_PAID | Orders — payment confirmed | Order confirmation |
| ORDER_SHIPPED | Orders — `POST /orders/{id}/ship` | Shipment notification |
| ORDER_DELIVERED | Orders — `POST /orders/{id}/deliver` | Delivery confirmation |
| ORDER_CANCELLED | Orders — customer cancel or `checkout.session.expired` | Cancellation notice |

`ORDER_PAID` and `ORDER_CANCELLED` fan out to both this service and production;
`ORDER_SHIPPED` and `ORDER_DELIVERED` are consumed only here. See
[docs/EVENT_CATALOG.md](../../docs/EVENT_CATALOG.md).

## Idempotency

Idempotency is **durable** and keyed by the outbox envelope's `event_id`. Each
successfully-sent email records one row in `notifications_schema.processed_events`;
a re-delivered event (same `event_id`) short-circuits to `already_processed` and
sends no second email. Because the record lives in Postgres — not an in-memory set —
this holds across a pod/container restart and with `replicaCount > 1`.

The record is written **after** a successful send (send → record), so there is a
narrow window: a crash between handing the email to the provider and committing the
row can re-send that one event once on redelivery. This is a deliberately accepted
rare duplicate, biased over silently dropping a customer email — it is **not**
exactly-once. On a send failure the service returns `503` and writes **no** row, so
the outbox retries with backoff.

## Metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| notifications_emails_sent_total | event_type, status | Emails handed to the provider |
| notifications_email_send_failures_total | event_type | Provider failures (each triggers an outbox retry) |

Scraped via the ServiceMonitor in `deploy/monitoring/servicemonitors.yaml`.

## Dependencies

- **Orders Service**: event producer — calls the `/events/*` endpoints via its outbox worker
- **AWS SES**: email transport when `EMAIL_PROVIDER=ses`
