from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
from starlette.responses import Response

SERVICE_NAME = "payments"

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
