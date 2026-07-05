import os
import time

from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

SERVICE_NAME = os.getenv("SERVICE_NAME", "notifications")

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

# Business metrics for transactional email delivery.
EMAILS_SENT = Counter(
    "notifications_emails_sent_total",
    "Emails sent by notifications service",
    ["event_type", "status"]
)
EMAIL_SEND_FAILURES = Counter(
    "notifications_email_send_failures_total",
    "Email send failures",
    ["event_type"]
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
