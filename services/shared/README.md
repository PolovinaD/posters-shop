# Shared Module

Shared utilities used across all Python services.

## Contents

### service_auth.py

Service-to-service authentication for the endpoints only another service is
meant to call. The ALB routes `/api/<service>` straight to each Service, so
those routes are reachable from the internet; they cannot take the customer JWT
dependency because the callers are background workers with no user in context.

A caller mints a short-lived HS256 token carrying `role="service"`, signed with
the `JWT_SECRET` the platform already distributes — no new secret. A callee
accepts that or a genuine owner token.

**Usage — caller:**

```python
from service_auth import internal_headers
async with httpx.AsyncClient(headers=internal_headers()) as client:
    ...
```

**Usage — callee:**

```python
from service_auth import require_service_or_owner

@app.post("/events/order-paid")
def handle(event: Payload, claims: dict = Depends(require_service_or_owner)):
    ...
```

Requires `JWT_SECRET` and `PyJWT` in the service. Note the trade-off documented
in the module: the secret is symmetric, so any holder can *mint* any role, not
just verify one. Asymmetric signing is the proper end state.

### logger.py

Structured JSON logging with correlation ID support.

**Features:**
- JSON-formatted log output
- Configurable log level via `LOG_LEVEL` env var
- Service name from `SERVICE_NAME` env var
- Correlation ID propagation via `X-Correlation-ID` header
- FastAPI middleware for request logging

**Usage:**

```python
from logger import get_logger, LoggingMiddleware

# Get logger instance
logger = get_logger(__name__)

# Use structured logging
logger.info("Order created", order_id=123, customer="user@example.com")
logger.error("Failed to process", error=str(e), order_id=123)

# Add middleware to FastAPI app
app.add_middleware(LoggingMiddleware)
```

**Output format:**
```json
{
  "timestamp": "2024-01-15T10:30:00.123456Z",
  "level": "INFO",
  "service": "orders",
  "correlation_id": "abc-123-def",
  "message": "Order created",
  "order_id": 123,
  "customer": "user@example.com"
}
```

**Middleware behavior:**
- Extracts or generates `X-Correlation-ID`
- Logs request start (method, path, correlation_id)
- Logs request end (status_code, duration_ms)
- Adds correlation_id to response headers

### bulkhead.py

Per-process bulkhead for the eight DB-backed services (orders, catalog, inventory,
users, logistics, production, notifications, designs). A pure-ASGI middleware holds an
`asyncio.Semaphore(pool_size + max_overflow)` from before the router runs until the
response has been sent, so at most that many requests are inside the service at once
and no more than that many threads can ever wait on the connection pool. Excess
requests wait on the event loop (no thread, no connection) for up to
`BULKHEAD_QUEUE_TIMEOUT` and are then answered
`503 {"detail": "Service busy, retry shortly"}` with `Retry-After: 1`.
`/healthz`, `/readyz`, `/metrics` and OPTIONS never wait for a slot. Why: FastAPI runs
`def` handlers, `run_in_threadpool` steps and response validation on one 40-token
threadpool, so a burst above the pool size used to park every token in a pool wait and
deadlock the process for `pool_timeout` (see `tests/load/README.md`).

**Usage** — the FIRST `add_middleware` call, immediately above `LoggingMiddleware`
(Starlette's first `add_middleware` is the innermost layer, so the request log and the
metrics middleware still see every shed request):

```python
from bulkhead import BulkheadMiddleware, bulkhead_limit, bulkhead_queue_timeout
from database import engine

app.add_middleware(
    BulkheadMiddleware,
    limit=bulkhead_limit(engine),
    queue_timeout=bulkhead_queue_timeout(),
)
app.add_middleware(LoggingMiddleware)
```

**Environment:**

| Variable | Default | Meaning |
|----------|---------|---------|
| `BULKHEAD_LIMIT` | `engine.pool.size() + engine.pool._max_overflow` (8 for orders, 10 elsewhere) | concurrent requests admitted; must be >= 1 |
| `BULKHEAD_QUEUE_TIMEOUT` | `10` | seconds a request may wait for a slot before the 503; must be > 0 |

**Metrics** (all carry a `service` label; once scraped on EKS the ServiceMonitor's
target label wins and the metric's own label is renamed `exported_service`, as the
circuit-breaker dashboard already queries):

| Metric | Type | Meaning |
|--------|------|---------|
| `bulkhead_in_flight` | gauge | requests currently admitted past the bulkhead |
| `bulkhead_queued` | gauge | requests waiting for a slot |
| `bulkhead_rejected_total` | counter | requests answered 503 because no slot freed within the queue timeout |

All three are materialised at 0 when the middleware stack is built (at startup under
uvicorn), so a scrape before the first request reads `0`, not "No data". The
`LoggingMiddleware` logs every shed request as `Request completed` at WARNING with
its correlation id and a `duration_ms` that includes the queue wait, and
`http_requests_total{status="503"}` counts it too (with `path="unknown"`, since no
route matched).

No Grafana panel yet — the circuit-breaker dashboard exists twice (JSON + inline
ConfigMap) and cannot be verified without a cluster; suggested panels:
`sum by (exported_service) (bulkhead_in_flight)`,
`sum by (exported_service) (bulkhead_queued)`,
`sum by (exported_service) (rate(bulkhead_rejected_total[1m]))`.

**Copy rule:** `services/shared/bulkhead.py` is canonical; the eight DB-backed
services carry a byte-identical `bulkhead.py` (`tests/unit/test_bulkhead.py` fails on
drift). payments and infra have no connection pool to size against and do not carry
it. The module imports only `prometheus_client`, `starlette` and the service's
`logger`; it deliberately does not import from `metrics`.

## Installation

The shared module is copied into each service's Docker image or symlinked for local development.

**Docker (copy approach):**
```dockerfile
COPY services/shared/logger.py /app/logger.py
COPY services/shared/bulkhead.py /app/bulkhead.py   # DB-backed services only
```

**Local development (symlink):**
```bash
cd services/orders
ln -s ../shared/logger.py logger.py
ln -s ../shared/bulkhead.py bulkhead.py
```

## Log Levels

| Level | Use Case |
|-------|----------|
| DEBUG | Detailed debugging info |
| INFO | General operational messages |
| WARNING | Something unexpected but handled |
| ERROR | Something failed |

Configure via environment:
```bash
export LOG_LEVEL=DEBUG  # More verbose
export LOG_LEVEL=WARNING  # Less verbose
```
