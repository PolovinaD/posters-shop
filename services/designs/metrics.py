import os
import time

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

SERVICE_NAME = os.getenv("SERVICE_NAME", "designs")

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

# Business metrics for the AI poster studio.
GENERATIONS_TOTAL = Counter(
    "designs_generations_total",
    "Generations finished, by provider and final status",
    ["provider", "status"]
)
PROVIDER_LATENCY = Histogram(
    "designs_provider_latency_seconds",
    "Image provider call latency",
    ["provider"],
    buckets=[1, 2, 5, 10, 20, 30, 60, 90, 120, 180]
)
QUEUE_DEPTH = Gauge(
    "designs_queue_depth",
    "Generations waiting in status queued"
)

# Same name and labels as orders' counter so the existing Grafana circuit-breaker
# panel picks the designs breaker up (circuit_breaker.py imports this).
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
