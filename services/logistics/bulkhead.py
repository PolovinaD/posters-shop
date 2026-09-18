"""Per-process bulkhead: admit at most `pool_size + max_overflow` requests at once.

Why it exists. FastAPI runs `def` handler bodies, `run_in_threadpool` steps AND the
response-model validation of `def` endpoints on ONE anyio threadpool of 40 tokens per
process, while each DB-backed service's SQLAlchemy pool holds 8-10 connections. A burst
above ~40 requests parks every token inside `pool.connect()` waits; the connection
holders then cannot get a token to serialise their response and reach the `get_db`
teardown that returns the connection, so nothing moves until `pool_timeout` fires and
the batch ends as 40 x 500 / 10 x 200 after 30 s.

The fix, by construction: a pure-ASGI middleware holding an `asyncio.Semaphore(limit)`
from before the router runs until the response has been sent. Excess requests wait ON
THE EVENT LOOP (no thread, no connection) for at most BULKHEAD_QUEUE_TIMEOUT and are
then answered `503 {"detail": "Service busy, retry shortly"}` + `Retry-After: 1`.

Sizing rule: limit = engine.pool.size() + engine.pool._max_overflow (BULKHEAD_LIMIT
overrides), so at most `limit` threads can ever be inside a pool wait and the holders
always find a token. /healthz, /readyz, /metrics and OPTIONS never wait for a slot.
Copy this file byte-identical into every DB-backed service (tests/unit/test_bulkhead.py
enforces it); payments and infra have no pool to size against and do not carry it.
"""
import asyncio
import os
import weakref

from prometheus_client import Counter, Gauge, REGISTRY
from starlette.responses import JSONResponse

from logger import get_logger

EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})
DEFAULT_QUEUE_TIMEOUT = 10.0   # seconds a request may wait for a slot (BULKHEAD_QUEUE_TIMEOUT)
FALLBACK_LIMIT = 10            # when the engine's pool cannot be read (unit tests stub it)
BUSY_DETAIL = "Service busy, retry shortly"
RETRY_AFTER_SECONDS = "1"

_log = get_logger("bulkhead")
_METRICS = weakref.WeakKeyDictionary()   # registry -> _Metrics, created once per registry


class _Metrics:
    def __init__(self, registry):
        self.in_flight = Gauge(
            "bulkhead_in_flight",
            "Requests currently admitted past the bulkhead",
            ["service"],
            registry=registry,
        )
        self.queued = Gauge(
            "bulkhead_queued",
            "Requests waiting for a bulkhead slot",
            ["service"],
            registry=registry,
        )
        self.rejected = Counter(
            "bulkhead_rejected_total",
            "Requests answered 503 because no slot freed within BULKHEAD_QUEUE_TIMEOUT",
            ["service"],
            registry=registry,
        )


class BulkheadMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware): admits at most `limit` HTTP requests at once,
    queues the rest on the event loop for up to `queue_timeout` seconds, then sheds them
    with a fast 503 + Retry-After. Register it FIRST (innermost) so the request log and
    the metrics middleware still see every shed request."""

    def __init__(
        self,
        app,
        limit,
        queue_timeout=DEFAULT_QUEUE_TIMEOUT,
        exempt_paths=EXEMPT_PATHS,
        service=None,
        registry=None,
    ):
        self.app = app
        self.limit = int(limit)
        self.queue_timeout = float(queue_timeout)
        self.exempt_paths = frozenset(exempt_paths)
        self.service = service or os.getenv("SERVICE_NAME", "unknown")
        self._sem = asyncio.Semaphore(self.limit)
        m = _metrics_for(registry)
        self._in_flight = m.in_flight.labels(service=self.service)
        self._queued = m.queued.labels(service=self.service)
        self._rejected = m.rejected.labels(service=self.service)
        # Materialise the children now: a scrape before the first request reads "0", not absent.
        self._in_flight.set(0)
        self._queued.set(0)
        self._rejected.inc(0)
        _log.info(
            "Bulkhead configured",
            service=self.service,
            limit=self.limit,
            queue_timeout=self.queue_timeout,
        )

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") == "OPTIONS"
            or _route_path(scope) in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return
        if self._sem.locked():
            self._queued.inc()
            try:
                await asyncio.wait_for(self._sem.acquire(), timeout=self.queue_timeout)
            except TimeoutError:
                self._rejected.inc()
                await _busy_response()(scope, receive, send)
                return
            finally:
                self._queued.dec()
        else:
            await self._sem.acquire()   # not locked: cannot block, no Task, gauge stays exact
        self._in_flight.inc()
        try:
            await self.app(scope, receive, send)
        finally:
            self._in_flight.dec()
            self._sem.release()


def bulkhead_limit(engine) -> int:
    """BULKHEAD_LIMIT if set and non-empty (>= 1, else ValueError), otherwise
    pool_size + max_overflow read from the engine (FALLBACK_LIMIT when unreadable)."""
    raw = os.getenv("BULKHEAD_LIMIT", "").strip()
    if raw:
        limit = int(raw)
        if limit < 1:
            raise ValueError("BULKHEAD_LIMIT must be >= 1")
        return limit
    return pool_capacity(engine)


def bulkhead_queue_timeout() -> float:
    """BULKHEAD_QUEUE_TIMEOUT in seconds (> 0, else ValueError), default 10."""
    raw = os.getenv("BULKHEAD_QUEUE_TIMEOUT", "").strip()
    timeout = float(raw) if raw else DEFAULT_QUEUE_TIMEOUT
    if timeout <= 0:
        raise ValueError("BULKHEAD_QUEUE_TIMEOUT must be > 0")
    return timeout


def pool_capacity(engine, fallback=FALLBACK_LIMIT) -> int:
    try:
        size = engine.pool.size()
        overflow = getattr(engine.pool, "_max_overflow", 0)
    except Exception:
        return fallback
    if isinstance(size, int) and isinstance(overflow, int):
        return max(1, size + max(overflow, 0))   # -1 = unlimited overflow -> size only
    return fallback


def _metrics_for(registry):
    reg = REGISTRY if registry is None else registry
    if reg not in _METRICS:
        try:
            _METRICS[reg] = _Metrics(reg)
        except ValueError:
            # Another copy of this module already registered the names in this registry
            # (unit tests load several services per process): fall back to unregistered.
            _METRICS[reg] = _Metrics(None)
    return _METRICS[reg]


def _route_path(scope) -> str:
    path = scope.get("path", "")
    root = scope.get("root_path", "")
    if root and path.startswith(root):
        return path[len(root):] or "/"
    return path


def _busy_response():
    return JSONResponse(
        {"detail": BUSY_DETAIL},
        status_code=503,
        headers={"Retry-After": RETRY_AFTER_SECONDS},
    )
