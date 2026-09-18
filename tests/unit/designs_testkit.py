"""Shared loader for the designs service's unit tests (NOT collected: no test_ prefix).

`load_designs()` imports the services/designs modules ONCE per pytest process under
unique "designs_<name>" aliases with `database` and `metrics` stubbed, and caches the
result. The real metrics.py must never be loaded twice in one process:
prometheus_client raises "Duplicated timeseries in CollectorRegistry" because
http_requests_total is already registered by test_inventory_reservation.py.

Isolation follows tests/unit/test_inventory_reservation.py: modules are registered
under BOTH the alias and the bare name while loading so intra-service imports
(`from providers import ...`) resolve to the designs copy, then the bare names are
popped. `database` is deliberately left installed (main.py keeps a live reference to
its get_db), as in test_inventory_reservation.py.
"""
import importlib.util
import os
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import DeclarativeBase

DESIGNS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/designs"))
# Load order matters: leaves first. Later plans append names here (quota, schemas, worker, main, summarizer, ...).
MODULES = ["logger", "service_auth", "auth", "models", "circuit_breaker", "providers", "summarizer", "storage", "quota", "schemas", "style_profile", "worker", "catalog_client", "inventory_client", "printing", "events", "main"]
_cache = None


async def _noop_track_metrics(request, call_next):
    return await call_next(request)


def _metrics_stub():
    m = types.ModuleType("metrics")
    m.SERVICE_NAME = "designs"
    m.track_metrics = _noop_track_metrics
    m.metrics_endpoint = MagicMock(return_value="")
    for name in (
        "REQUEST_COUNT", "REQUEST_LATENCY", "GENERATIONS_TOTAL", "PROVIDER_LATENCY",
        "QUEUE_DEPTH", "CIRCUIT_BREAKER_STATE_TRANSITIONS",
    ):
        setattr(m, name, MagicMock())
    return m


def load_designs():
    global _cache
    if _cache is not None:
        return _cache
    os.environ.setdefault("JWT_SECRET", "unit-test-secret")
    os.environ["DESIGNS_STORAGE_DIR"] = tempfile.mkdtemp(prefix="designs-unit-")
    os.environ["STORAGE_BACKEND"] = "local"
    os.environ["IMAGE_PROVIDER"] = "fake"
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("REPLICATE_API_TOKEN", None)

    class _Base(DeclarativeBase):
        pass

    db = types.ModuleType("database")
    db.Base = _Base
    db.engine = MagicMock()
    db.SessionLocal = MagicMock()

    def _get_db():
        yield db.SessionLocal()

    db.get_db = _get_db
    sys.modules["database"] = db
    sys.modules["metrics"] = _metrics_stub()
    loaded = {"db": db, "metrics": sys.modules["metrics"]}
    sys.path.insert(0, DESIGNS_DIR)
    try:
        for name in MODULES:
            path = os.path.join(DESIGNS_DIR, f"{name}.py")
            if not os.path.exists(path):
                continue
            spec = importlib.util.spec_from_file_location(f"designs_{name}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"designs_{name}"] = mod
            sys.modules[name] = mod  # bare name during loading: intra-service imports hit THIS copy
            spec.loader.exec_module(mod)
            loaded[name] = mod
    finally:
        sys.path.remove(DESIGNS_DIR)
        for name in MODULES + ["metrics"]:
            sys.modules.pop(name, None)
        # "database" is deliberately left installed (main.py keeps a live reference to get_db),
        # as in test_inventory_reservation.py
    _cache = SimpleNamespace(**loaded)
    return _cache
