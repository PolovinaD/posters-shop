"""Unit tests for services/shared/bulkhead.py — the per-process bulkhead middleware.

Every case drives a throwaway FastAPI app through httpx.ASGITransport under
asyncio.run, with its own prometheus_client.CollectorRegistry so nothing touches the
global REGISTRY. The shared module is loaded once under the alias `shared_bulkhead`
with services/shared temporarily on sys.path so its `from logger import get_logger`
resolves to the shared logger; whatever `sys.modules["logger"]` held before is restored.
"""
import asyncio
import importlib.util
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from starlette.middleware.base import BaseHTTPMiddleware

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_DIR = REPO_ROOT / "services" / "shared"
SHARED_BULKHEAD = SHARED_DIR / "bulkhead.py"
DB_SERVICES = [
    "orders", "catalog", "inventory", "users", "logistics", "production",
    "notifications", "designs",
]


def _load_shared_bulkhead():
    previous_logger = sys.modules.get("logger")
    sys.modules.pop("logger", None)
    sys.path.insert(0, str(SHARED_DIR))
    try:
        spec = importlib.util.spec_from_file_location("shared_bulkhead", SHARED_BULKHEAD)
        module = importlib.util.module_from_spec(spec)
        sys.modules["shared_bulkhead"] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SHARED_DIR))
        if previous_logger is not None:
            sys.modules["logger"] = previous_logger
        else:
            sys.modules.pop("logger", None)
    return module


shared_bulkhead = _load_shared_bulkhead()
SERVICE = "unit"


class _PassThrough(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


def make_app(limit, queue_timeout, registry, root_path=""):
    """Bulkhead FIRST (innermost), then a BaseHTTPMiddleware and CORS, like the real stack."""
    gate = asyncio.Event()
    app = FastAPI(root_path=root_path)

    @app.get("/work")
    async def work():
        await gate.wait()
        return {"ok": True}

    @app.options("/work")
    async def work_options():
        return {"ok": True}

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        return {"status": "ready"}

    @app.get("/metrics")
    async def metrics():
        return {"metrics": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    @app.get("/bad")
    async def bad():
        raise HTTPException(status_code=400, detail="bad")

    app.add_middleware(
        shared_bulkhead.BulkheadMiddleware,
        limit=limit,
        queue_timeout=queue_timeout,
        service=SERVICE,
        registry=registry,
    )
    app.add_middleware(_PassThrough)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    return app, gate


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def sample(registry, name):
    return registry.get_sample_value(name, {"service": SERVICE})


def test_admits_up_to_limit_and_queues_the_rest():
    registry = CollectorRegistry()
    app, gate = make_app(limit=2, queue_timeout=5, registry=registry)

    async def scenario():
        async with client_for(app) as c:
            tasks = [asyncio.create_task(c.get("/work")) for _ in range(3)]
            await asyncio.sleep(0.05)
            assert sample(registry, "bulkhead_in_flight") == 2.0
            assert sample(registry, "bulkhead_queued") == 1.0
            gate.set()
            responses = await asyncio.gather(*tasks)
            assert [r.status_code for r in responses] == [200, 200, 200]
        assert sample(registry, "bulkhead_in_flight") == 0.0
        assert sample(registry, "bulkhead_queued") == 0.0
        assert sample(registry, "bulkhead_rejected_total") == 0.0

    asyncio.run(scenario())


def test_rejects_with_503_retry_after_when_queue_timeout_expires():
    registry = CollectorRegistry()
    app, gate = make_app(limit=1, queue_timeout=0.1, registry=registry)

    async def scenario():
        async with client_for(app) as c:
            first = asyncio.create_task(c.get("/work"))
            await asyncio.sleep(0.05)
            assert sample(registry, "bulkhead_in_flight") == 1.0
            r = await c.get("/work")
            assert r.status_code == 503
            assert r.headers["retry-after"] == "1"
            assert r.json() == {"detail": "Service busy, retry shortly"}
            assert sample(registry, "bulkhead_rejected_total") == 1.0
            assert sample(registry, "bulkhead_queued") == 0.0
            gate.set()
            assert (await first).status_code == 200
            assert (await c.get("/work")).status_code == 200  # slot was not leaked
        assert sample(registry, "bulkhead_in_flight") == 0.0

    asyncio.run(scenario())


def test_exempt_paths_and_options_bypass_a_saturated_bulkhead():
    registry = CollectorRegistry()
    app, gate = make_app(limit=1, queue_timeout=5, registry=registry)

    async def scenario():
        async with client_for(app) as c:
            held = asyncio.create_task(c.get("/work"))
            await asyncio.sleep(0.05)
            assert sample(registry, "bulkhead_in_flight") == 1.0
            for path in ("/healthz", "/readyz", "/metrics"):
                r = await asyncio.wait_for(c.get(path), 1.0)
                assert r.status_code == 200, path
            r = await asyncio.wait_for(c.options("/work"), 1.0)
            assert r.status_code == 200
            assert sample(registry, "bulkhead_in_flight") == 1.0
            assert sample(registry, "bulkhead_queued") == 0.0
            gate.set()
            assert (await held).status_code == 200

    asyncio.run(scenario())


def test_root_path_prefix_is_stripped_before_the_exemption_check():
    registry = CollectorRegistry()
    app, gate = make_app(limit=1, queue_timeout=5, registry=registry, root_path="/api/orders")

    async def scenario():
        async with client_for(app) as c:
            held = asyncio.create_task(c.get("/work"))
            await asyncio.sleep(0.05)
            assert sample(registry, "bulkhead_in_flight") == 1.0
            for path in ("/healthz", "/api/orders/healthz"):
                r = await asyncio.wait_for(c.get(path), 1.0)
                assert r.status_code == 200, path
            gate.set()
            assert (await held).status_code == 200

    asyncio.run(scenario())


def test_slot_released_after_unhandled_exception_and_http_exception():
    registry = CollectorRegistry()
    app, gate = make_app(limit=1, queue_timeout=0.2, registry=registry)
    gate.set()

    async def scenario():
        async with client_for(app) as c:
            with pytest.raises(RuntimeError):
                await c.get("/boom")
            assert sample(registry, "bulkhead_in_flight") == 0.0
            assert (await c.get("/work")).status_code == 200
            assert (await c.get("/bad")).status_code == 400
            assert sample(registry, "bulkhead_in_flight") == 0.0
            assert (await c.get("/work")).status_code == 200
        assert sample(registry, "bulkhead_rejected_total") == 0.0

    asyncio.run(scenario())


def test_limit_from_engine_pool_env_override_and_fallback(monkeypatch):
    engine = create_engine("postgresql+psycopg2://u:p@localhost:1/db", pool_size=3, max_overflow=5)
    monkeypatch.delenv("BULKHEAD_LIMIT", raising=False)
    assert shared_bulkhead.bulkhead_limit(engine) == 8
    assert shared_bulkhead.bulkhead_limit(MagicMock()) == shared_bulkhead.FALLBACK_LIMIT == 10
    monkeypatch.setenv("BULKHEAD_LIMIT", "16")
    assert shared_bulkhead.bulkhead_limit(engine) == 16
    monkeypatch.setenv("BULKHEAD_LIMIT", "")
    assert shared_bulkhead.bulkhead_limit(engine) == 8
    monkeypatch.setenv("BULKHEAD_LIMIT", "0")
    with pytest.raises(ValueError):
        shared_bulkhead.bulkhead_limit(engine)
    monkeypatch.setenv("BULKHEAD_LIMIT", "x")
    with pytest.raises(ValueError):
        shared_bulkhead.bulkhead_limit(engine)


def test_queue_timeout_from_env(monkeypatch):
    monkeypatch.delenv("BULKHEAD_QUEUE_TIMEOUT", raising=False)
    assert shared_bulkhead.bulkhead_queue_timeout() == 10.0
    monkeypatch.setenv("BULKHEAD_QUEUE_TIMEOUT", "2.5")
    assert shared_bulkhead.bulkhead_queue_timeout() == 2.5
    monkeypatch.setenv("BULKHEAD_QUEUE_TIMEOUT", "0")
    with pytest.raises(ValueError):
        shared_bulkhead.bulkhead_queue_timeout()


def test_metric_children_exist_at_zero_after_stack_build():
    """GAUGE-01 lesson: a scrape before the first request must read 0, not 'No data'."""
    registry = CollectorRegistry()
    app, _gate = make_app(limit=2, queue_timeout=5, registry=registry)
    names = ("bulkhead_in_flight", "bulkhead_queued", "bulkhead_rejected_total")
    assert [sample(registry, n) for n in names] == [None, None, None]
    app.middleware_stack = app.build_middleware_stack()
    assert [sample(registry, n) for n in names] == [0.0, 0.0, 0.0]


def test_service_copies_match_shared():
    expected = SHARED_BULKHEAD.read_bytes()
    for svc in DB_SERVICES:
        copy = REPO_ROOT / "services" / svc / "bulkhead.py"
        assert copy.read_bytes() == expected, f"{svc}/bulkhead.py drifted from shared/bulkhead.py"


@pytest.mark.parametrize("svc", DB_SERVICES)
def test_registered_innermost_in_every_db_backed_service(svc):
    """First add_middleware = innermost: the bulkhead must be registered before LoggingMiddleware."""
    text = (REPO_ROOT / "services" / svc / "main.py").read_text()
    bulkhead = re.search(r"add_middleware\(\s*BulkheadMiddleware", text)
    assert bulkhead is not None, f"{svc}/main.py does not register BulkheadMiddleware"
    logging_at = text.index("add_middleware(LoggingMiddleware)")
    assert 0 < bulkhead.start() < logging_at, f"{svc}: bulkhead is not the innermost middleware"
