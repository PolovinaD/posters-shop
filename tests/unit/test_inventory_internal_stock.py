"""
Unit tests for inventory `POST /internal/stock` — the idempotent bulk stock create
the designs service calls at Print-this to give print-on-demand SKUs their
"virtual stock" (D-11, 09-04).

No database or network: the route function is called directly with a MagicMock
session. Module isolation is the test_inventory_reservation.py bootstrap with its
own `inventory2_*` aliases (two test files must not share module globals) and a
STUB `metrics` module — the real inventory metrics.py registers http_requests_total
and prometheus_client raises on the duplicate when test_inventory_reservation.py
loads it later in the same process.
"""
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import DeclarativeBase

_INVENTORY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/inventory"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"inventory2_{name}", os.path.join(_INVENTORY_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"inventory2_{name}"] = mod
    sys.modules[name] = mod  # bare name while loading so main.py's intra-service imports hit this copy
    spec.loader.exec_module(mod)
    return mod


class _RealBase(DeclarativeBase):
    pass


async def _noop_track_metrics(request, call_next):
    return await call_next(request)


os.environ.setdefault("JWT_SECRET", "unit-test-secret")

_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()
sys.modules["database"] = _db_stub

_metrics_stub = types.ModuleType("metrics")
_metrics_stub.SERVICE_NAME = "inventory"
_metrics_stub.track_metrics = _noop_track_metrics
_metrics_stub.metrics_endpoint = MagicMock(return_value="")
for _name in ("STOCK_LEVEL", "ACTIVE_RESERVATIONS", "RESERVATIONS_EXPIRED"):
    setattr(_metrics_stub, _name, MagicMock())
sys.modules["metrics"] = _metrics_stub

sys.path.insert(0, _INVENTORY_DIR)
try:
    _load("logger")
    _load("service_auth")
    _load("auth")
    inv_models = _load("models")
    inv_schemas = _load("schemas")
    inv_main = _load("main")
finally:
    sys.path.remove(_INVENTORY_DIR)
    for _name in ("logger", "service_auth", "auth", "models", "schemas", "main", "metrics"):
        sys.modules.pop(_name, None)
    # "database" stays installed: main.py keeps a live reference to its get_db.

Stock = inv_models.Stock
InternalStockCreate = inv_schemas.InternalStockCreate
STOCK_LEVEL = _metrics_stub.STOCK_LEVEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_with_existing(existing_skus):
    """Session whose pre-check `select(Stock.sku).where(...)` answers `existing_skus`."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = list(existing_skus)
    return db


def _payload(*skus, available=1000):
    return InternalStockCreate(items=[{"sku": s, "name": f"Custom: x ({s[-2:]})", "available": available} for s in skus])


def _guards(path: str, method: str) -> list[str]:
    route = [r for r in inv_main.app.routes if getattr(r, "path", None) == path and method in r.methods][0]
    # the stubbed get_db is a MagicMock without __name__
    return [getattr(dep.call, "__name__", type(dep.call).__name__) for dep in route.dependant.dependencies]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_internal_stock_creates_missing_and_skips_existing():
    STOCK_LEVEL.reset_mock()
    db = _db_with_existing(["AI-7-A3"])
    out = inv_main.create_internal_stock(_payload("AI-7-A4", "AI-7-A3"), db=db, _={})

    assert out.created == ["AI-7-A4"]
    assert out.skipped == ["AI-7-A3"]
    assert db.add.call_count == 1
    added = db.add.call_args.args[0]
    assert isinstance(added, Stock)
    assert added.sku == "AI-7-A4" and added.name == "Custom: x (A4)"
    assert added.available == 1000 and added.reserved == 0
    assert db.commit.call_count == 1
    STOCK_LEVEL.labels.assert_called_once_with(sku="AI-7-A4")
    STOCK_LEVEL.labels.return_value.set.assert_called_once_with(1000)


def test_internal_stock_all_existing_is_noop_200():
    STOCK_LEVEL.reset_mock()
    db = _db_with_existing(["AI-7-A4", "AI-7-A3"])
    out = inv_main.create_internal_stock(_payload("AI-7-A4", "AI-7-A3"), db=db, _={})

    assert out.created == []
    assert out.skipped == ["AI-7-A4", "AI-7-A3"]
    db.add.assert_not_called()
    STOCK_LEVEL.labels.assert_not_called()
    # a second call with the same body would also answer 200: the route has no non-200 status
    route = [r for r in inv_main.app.routes if getattr(r, "path", None) == "/internal/stock"][0]
    assert route.status_code in (None, 200)


def test_internal_stock_duplicate_sku_in_one_body_is_created_once():
    db = _db_with_existing([])
    out = inv_main.create_internal_stock(_payload("AI-7-A4", "AI-7-A4"), db=db, _={})
    assert out.created == ["AI-7-A4"]
    assert out.skipped == ["AI-7-A4"]
    assert db.add.call_count == 1


def test_internal_stock_validates_items():
    with pytest.raises(ValidationError):
        InternalStockCreate(items=[])
    with pytest.raises(ValidationError):
        InternalStockCreate(items=[{"sku": "AI-7-A4", "name": "x", "available": -1}])
    with pytest.raises(ValidationError):
        InternalStockCreate(items=[{"sku": "", "name": "x", "available": 1}])
    with pytest.raises(ValidationError):
        InternalStockCreate(items=[{"sku": f"S-{i}", "name": "x", "available": 1} for i in range(51)])
    ok = InternalStockCreate(items=[{"sku": "AI-7-A4", "name": "x"}])
    assert ok.items[0].available == 0


def test_internal_stock_route_guard():
    names = _guards("/internal/stock", "POST")
    assert "require_service_or_owner" in names
    assert "require_owner" not in names
    # the owner endpoint is untouched
    assert "require_owner" in _guards("/stock", "POST")
