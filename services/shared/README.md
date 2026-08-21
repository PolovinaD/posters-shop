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

## Installation

The shared module is copied into each service's Docker image or symlinked for local development.

**Docker (copy approach):**
```dockerfile
COPY services/shared/logger.py /app/logger.py
```

**Local development (symlink):**
```bash
cd services/orders
ln -s ../shared/logger.py logger.py
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
