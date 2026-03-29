from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
from starlette.responses import Response

SERVICE_NAME = "orders"

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "path", "status"]
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency in seconds",
    ["service", "path"]
)

# Orders-specific metrics
ORDERS_CREATED = Counter(
    "orders_created_total",
    "Total orders created",
    []
)

ORDERS_BY_STATUS = Gauge(
    "orders_by_status",
    "Current orders by status",
    ["status"]
)

ORDER_TOTAL_AMOUNT = Histogram(
    "order_total_amount",
    "Order total amount distribution",
    [],
    buckets=[10, 25, 50, 100, 200, 500, 1000]
)

INVENTORY_RESERVATION_FAILURES = Counter(
    "inventory_reservation_failures_total",
    "Failed inventory reservations",
    ["reason"]
)

CIRCUIT_BREAKER_STATE_TRANSITIONS = Counter(
    "circuit_breaker_state_transitions_total",
    "Circuit breaker state transitions",
    ["service", "from_state", "to_state"]
)


def metrics_endpoint():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def track_metrics(request, call_next):
    """Middleware for counting and timing requests."""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    route = request.scope.get("route")
    path = getattr(route, "path", "unknown")

    REQUEST_COUNT.labels(
        service=SERVICE_NAME,
        method=request.method,
        path=path,
        status=response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        service=SERVICE_NAME,
        path=path
    ).observe(duration)

    return response
