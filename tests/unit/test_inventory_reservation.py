"""
Unit tests for inventory reservation logic.
All functions are tested by injecting a MagicMock SQLAlchemy session.
No database or network required.

Module isolation strategy:
  All inventory service modules (models, schemas, metrics, logger, main) are loaded
  with unique "inventory_*" names via importlib so they don't clash with identically-
  named modules from other services (e.g. services/orders/models.py). sys.path is
  temporarily modified only while loading, then immediately restored.
"""
import sys
import os
import types
import importlib
import importlib.util
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException

_INVENTORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/inventory")
)


def _load_inventory_module(name: str):
    """Load a module from services/inventory/ as 'inventory_{name}' to avoid collisions."""
    spec = importlib.util.spec_from_file_location(
        f"inventory_{name}",
        os.path.join(_INVENTORY_DIR, f"{name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"inventory_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Bootstrap: set up sys.modules aliases so that when inventory/main.py does
# `from database import ...` or `from models import ...`, it gets our stubs/
# real inventory modules (not orders or other service modules).
# We add _INVENTORY_DIR to sys.path only briefly, then remove it.
# ---------------------------------------------------------------------------

# 1. Stub `database` with a real DeclarativeBase so SQLAlchemy mapped classes work.
from sqlalchemy.orm import DeclarativeBase  # noqa: E402


class _RealBase(DeclarativeBase):
    pass


_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()
sys.modules["database"] = _db_stub

# 2. Load inventory sub-modules with the inventory dir on path temporarily.
sys.path.insert(0, _INVENTORY_DIR)
try:
    _inv_models = _load_inventory_module("models")
    sys.modules["models"] = _inv_models         # alias so main.py `from models import` works

    _inv_schemas = _load_inventory_module("schemas")
    sys.modules["schemas"] = _inv_schemas

    _inv_logger = _load_inventory_module("logger")
    sys.modules["logger"] = _inv_logger

    _inv_metrics = _load_inventory_module("metrics")
    sys.modules["metrics"] = _inv_metrics

    # 3. Load main under a unique name so it doesn't collide with services/orders/main.py.
    _inv_main = _load_inventory_module("main")
    # Do NOT alias as sys.modules["main"] — we want isolation.
finally:
    sys.path.remove(_INVENTORY_DIR)
    # Restore generic module aliases to None so order-tests can re-register their own.
    # We keep "database" stub; orders test uses setdefault() which won't overwrite.
    # Remove inventory-specific aliases so test_order_state_machine.py can load its own.
    for _mod_name in ("models", "schemas", "logger", "metrics"):
        sys.modules.pop(_mod_name, None)

reserve_stock = _inv_main.reserve_stock
release_reservation = _inv_main.release_reservation
commit_reservation = _inv_main.commit_reservation


# ---------------------------------------------------------------------------
# Helpers — build mock DB sessions for different scenarios
# ---------------------------------------------------------------------------

def make_db_with_stock(available: int):
    """
    DB mock where the atomic UPDATE (reserve) succeeds and the stock record
    has `available` units remaining after decrement.
    fetchone() returning a non-None value means the UPDATE matched a row.
    refresh() is configured to set id=1 on the refreshed ORM object so that
    the ReserveResponse (which requires reservation_id: int) can be constructed.
    """
    db = MagicMock()
    result_row = MagicMock()
    result_row.available = available
    db.execute.return_value.fetchone.return_value = result_row

    def _refresh_side_effect(obj):
        obj.id = 1

    db.refresh.side_effect = _refresh_side_effect
    return db


def make_db_insufficient_stock():
    """
    DB mock where the atomic UPDATE finds no rows (available < quantity).
    fetchone() returns None. scalar_one_or_none returns a Stock with available=0.
    """
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    stock_mock = MagicMock()
    stock_mock.available = 0
    db.execute.return_value.scalar_one_or_none.return_value = stock_mock
    return db


def make_db_unknown_sku():
    """
    DB mock where the atomic UPDATE finds no rows AND scalar_one_or_none
    returns None (SKU does not exist at all).
    """
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None
    db.execute.return_value.scalar_one_or_none.return_value = None
    return db


def make_db_with_active_reservations():
    """
    DB mock that returns a list of active Reservation mocks for release/commit.
    """
    db = MagicMock()
    res1 = MagicMock()
    res1.quantity = 2
    res1.status = "active"
    db.execute.return_value.scalars.return_value.all.return_value = [res1]
    return db, res1


def make_db_no_active_reservations():
    """DB mock where no active reservations exist for a given order."""
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = []
    return db


# ---------------------------------------------------------------------------
# reserve_stock tests
# ---------------------------------------------------------------------------

def test_reserve_stock_success():
    """reserve_stock with sufficient stock creates a Reservation and commits."""
    import inspect

    db = make_db_with_stock(available=8)
    payload = MagicMock()
    payload.sku = "SKU-001"
    payload.quantity = 2
    payload.order_id = 1
    payload.ttl_minutes = 15

    if inspect.iscoroutinefunction(reserve_stock):
        import asyncio
        asyncio.get_event_loop().run_until_complete(reserve_stock(payload, db))
    else:
        reserve_stock(payload, db)

    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_reserve_stock_insufficient_raises_409():
    """reserve_stock with zero available raises HTTP 409."""
    import inspect

    db = make_db_insufficient_stock()
    payload = MagicMock()
    payload.sku = "SKU-001"
    payload.quantity = 5
    payload.order_id = 2
    payload.ttl_minutes = 15

    with pytest.raises(HTTPException) as exc_info:
        if inspect.iscoroutinefunction(reserve_stock):
            import asyncio
            asyncio.get_event_loop().run_until_complete(reserve_stock(payload, db))
        else:
            reserve_stock(payload, db)

    assert exc_info.value.status_code == 409


def test_reserve_stock_unknown_sku_raises_404():
    """reserve_stock with nonexistent SKU raises HTTP 404."""
    import inspect

    db = make_db_unknown_sku()
    payload = MagicMock()
    payload.sku = "SKU-MISSING"
    payload.quantity = 1
    payload.order_id = 3
    payload.ttl_minutes = 15

    with pytest.raises(HTTPException) as exc_info:
        if inspect.iscoroutinefunction(reserve_stock):
            import asyncio
            asyncio.get_event_loop().run_until_complete(reserve_stock(payload, db))
        else:
            reserve_stock(payload, db)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# release_reservation tests
# ---------------------------------------------------------------------------

def test_release_reservation_no_active_raises_404():
    """release_reservation with no active reservations raises HTTP 404."""
    import inspect

    db = make_db_no_active_reservations()
    payload = MagicMock()
    payload.order_id = 42
    payload.sku = None

    with pytest.raises(HTTPException) as exc_info:
        if inspect.iscoroutinefunction(release_reservation):
            import asyncio
            asyncio.get_event_loop().run_until_complete(release_reservation(payload, db))
        else:
            release_reservation(payload, db)

    assert exc_info.value.status_code == 404


def test_release_reservation_commits_on_success():
    """release_reservation with active reservations calls db.commit()."""
    import inspect

    db, res = make_db_with_active_reservations()
    payload = MagicMock()
    payload.order_id = 1
    payload.sku = None

    if inspect.iscoroutinefunction(release_reservation):
        import asyncio
        asyncio.get_event_loop().run_until_complete(release_reservation(payload, db))
    else:
        release_reservation(payload, db)

    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# commit_reservation tests
# ---------------------------------------------------------------------------

def test_commit_reservation_commits():
    """commit_reservation with active reservations marks them committed and commits."""
    import inspect

    db, res = make_db_with_active_reservations()
    payload = MagicMock()
    payload.order_id = 1
    payload.sku = None

    if inspect.iscoroutinefunction(commit_reservation):
        import asyncio
        asyncio.get_event_loop().run_until_complete(commit_reservation(payload, db))
    else:
        commit_reservation(payload, db)

    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# TTL / expiry logic test
# ---------------------------------------------------------------------------

def test_reservation_ttl_is_applied():
    """
    Verifies that the Reservation created by reserve_stock includes an expires_at
    field set in the future (TTL logic is applied).
    """
    import inspect
    from datetime import datetime, timezone

    db = make_db_with_stock(available=10)
    payload = MagicMock()
    payload.sku = "SKU-001"
    payload.quantity = 1
    payload.order_id = 99
    payload.ttl_minutes = 15

    if inspect.iscoroutinefunction(reserve_stock):
        import asyncio
        asyncio.get_event_loop().run_until_complete(reserve_stock(payload, db))
    else:
        reserve_stock(payload, db)

    # The Reservation object was passed to db.add() — inspect it
    call_args = db.add.call_args
    reservation = call_args[0][0]
    # expires_at should be set (not None) and after now
    assert hasattr(reservation, "expires_at"), "Reservation must have expires_at attribute"
    assert reservation.expires_at is not None, "expires_at must not be None"
    now = datetime.now(timezone.utc)
    # expires_at may be naive or aware — compare accordingly
    exp = reservation.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp > now, "expires_at must be in the future"
