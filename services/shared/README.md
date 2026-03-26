# Shared Module

Shared utilities used across all Python services.

## Contents

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
