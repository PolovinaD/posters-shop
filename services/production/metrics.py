from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import time
from starlette.responses import Response

SERVICE_NAME = "production"

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

# Production-specific metrics
JOBS_CREATED = Counter(
    "production_jobs_created_total",
    "Total production jobs created",
    []
)

JOBS_COMPLETED = Counter(
    "production_jobs_completed_total",
    "Total production jobs completed",
    ["status"]  # completed, failed
)

JOBS_BY_STATUS = Gauge(
    "production_jobs_by_status",
    "Current jobs by status",
    ["status"]
)

JOB_PROCESSING_TIME = Histogram(
    "production_job_processing_seconds",
    "Job processing time in seconds",
    [],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

JOBS_IN_QUEUE = Gauge(
    "production_jobs_queued",
    "Number of jobs waiting in queue",
    []
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
