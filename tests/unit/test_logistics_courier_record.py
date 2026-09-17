"""Unit tests for quick 260917-jrx: recording who bound the courier wallet on a shipment.

- services/logistics/worker_rules.py::courier_id_from_claims -- the pure rule deciding
  what `courier_id` records. `sub` is the user's EMAIL (users/main.py:94 mints
  sub=user.email); a service token's `service:<name>` is not a person -> None.
- services/logistics/main.py::update_shipment_status -- driven through FastAPI's
  TestClient with `database`, `logger`, `metrics`, `service_auth` and `orders_client`
  stubbed (the test_orders_escrow.py recipe) and the real `models`, `worker_rules`
  and `auth` loaded under aliases. No database, no network; the TestClient is never
  used as a context manager, so the lifespan and the shipment worker never start.
"""
import importlib.util
import os
import sys
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.orm import DeclarativeBase
from starlette.middleware.base import BaseHTTPMiddleware

_LOGISTICS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/logistics"))

WALLET_A = "0x" + "22" * 20
WALLET_B = "0x" + "33" * 20
COURIER_CLAIMS = {"sub": "courier@postershop.com", "role": "courier"}


def _load(name, alias):
    spec = importlib.util.spec_from_file_location(alias, os.path.join(_LOGISTICS_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


class _RealBase(DeclarativeBase):
    pass


class _NoopLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


async def _noop_track_metrics(request, call_next):
    return await call_next(request)


_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()

_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
_logger_stub.LoggingMiddleware = _NoopLoggingMiddleware

# The real metrics.py registers http_requests_total in prometheus_client's default
# registry; test_inventory_reservation.py already loaded inventory's copy of the
# same metric, so a second registration raises "Duplicated timeseries". Stub it.
_metrics_stub = types.ModuleType("metrics")
_metrics_stub.track_metrics = _noop_track_metrics
_metrics_stub.metrics_endpoint = MagicMock(return_value="")

_service_auth_stub = types.ModuleType("service_auth")
_service_auth_stub.require_service_or_owner = lambda: {"sub": "service:test", "role": "service"}
_service_auth_stub.internal_headers = lambda service_name=None: {}

_orders_client_stub = types.ModuleType("orders_client")
_orders_client_stub.notify_courier_assigned = AsyncMock(return_value=True)
_orders_client_stub.notify_order_delivered = AsyncMock(return_value=True)
_orders_client_stub.notify_order_shipped = AsyncMock(return_value=True)
_orders_client_stub.fetch_shipping_address = AsyncMock(return_value=None)

_NAMES = ("database", "logger", "metrics", "service_auth", "orders_client", "models", "worker_rules", "auth")
_previous = {n: sys.modules.get(n) for n in _NAMES}
sys.modules.update({
    "database": _db_stub, "logger": _logger_stub, "metrics": _metrics_stub,
    "service_auth": _service_auth_stub, "orders_client": _orders_client_stub,
})
sys.path.insert(0, _LOGISTICS_DIR)
try:
    _models = _load("models", "logistics_record_models")
    sys.modules["models"] = _models
    _rules = _load("worker_rules", "logistics_record_rules")
    sys.modules["worker_rules"] = _rules
    _auth = _load("auth", "logistics_record_auth")
    sys.modules["auth"] = _auth
    _main = _load("main", "logistics_main_record_test")   # last: binds the module objects above
finally:
    sys.path.remove(_LOGISTICS_DIR)
    for _n in _NAMES:
        if _previous[_n] is not None:
            sys.modules[_n] = _previous[_n]
        else:
            sys.modules.pop(_n, None)


def _dispatched_shipment():
    return _models.Shipment(id=1, order_id=784, status="dispatched", tracking="TRK-000784")


def _client(shipment, claims=COURIER_CLAIMS):
    """TestClient whose db.get returns `shipment`, authenticated as `claims`. Returns (client, db)."""
    from fastapi.testclient import TestClient

    db = MagicMock()
    db.get.return_value = shipment

    def override_get_db():
        yield db

    _main.app.dependency_overrides[_main.get_db] = override_get_db
    _main.app.dependency_overrides[_main.require_courier_or_admin] = lambda: claims
    return TestClient(_main.app, raise_server_exceptions=False), db


# ---------------------------------------------------------------------------
# courier_id_from_claims -- pure rule
# ---------------------------------------------------------------------------

def test_courier_id_from_claims():
    """JRX-01: a human token records its `sub` (the email); service tokens, missing/empty sub and None record nothing."""
    assert _rules.courier_id_from_claims(COURIER_CLAIMS) == "courier@postershop.com"
    assert _rules.courier_id_from_claims({"sub": "admin@postershop.com", "role": "owner"}) == "admin@postershop.com"
    assert _rules.courier_id_from_claims({"sub": "service:production", "role": "service"}) is None
    assert _rules.courier_id_from_claims({"role": "courier"}) is None
    assert _rules.courier_id_from_claims({"sub": ""}) is None
    assert _rules.courier_id_from_claims(None) is None


# ---------------------------------------------------------------------------
# Shipment model -- the three nullable columns
# ---------------------------------------------------------------------------

def test_shipment_model_has_courier_binding_columns():
    """JRX-01: Shipment maps courier_id, courier_wallet (String(42)) and courier_bound_at, all nullable."""
    cols = _models.Shipment.__table__.columns
    for name in ("courier_id", "courier_wallet", "courier_bound_at"):
        assert name in cols, f"Shipment.__table__ is missing {name}"
        assert cols[name].nullable, f"{name} must be nullable (rows bound before this change have none)"
    assert cols["courier_wallet"].type.length == 42


# ---------------------------------------------------------------------------
# PUT /shipments/{id}/status -- what the pick-up records
# ---------------------------------------------------------------------------

def test_pickup_records_courier_wallet_and_time(monkeypatch):
    """JRX-02: dispatched -> in_transit with an explicit wallet records the caller's sub, THAT wallet (explicit wins) and a timestamp, in the one commit, and still notifies orders."""
    monkeypatch.setattr(_main, "LOGISTICS_DEFAULT_COURIER_WALLET", WALLET_B)
    _orders_client_stub.notify_courier_assigned.reset_mock()
    s = _dispatched_shipment()
    client, db = _client(s)

    resp = client.put("/shipments/1/status", json={"status": "in_transit", "courier_wallet": WALLET_A})

    assert resp.status_code == 200, resp.text
    assert s.status == "in_transit"
    assert s.courier_id == "courier@postershop.com"
    assert s.courier_wallet == WALLET_A
    assert isinstance(s.courier_bound_at, datetime)

    body = resp.json()
    assert body["status"] == "in_transit"
    assert body["courier_id"] == "courier@postershop.com"
    assert body["courier_wallet"] == WALLET_A
    assert body["courier_bound_at"] == s.courier_bound_at.isoformat()

    db.commit.assert_called_once()
    _orders_client_stub.notify_courier_assigned.assert_awaited_once_with(784, WALLET_A)


def test_pickup_without_explicit_wallet_records_default_but_still_the_human(monkeypatch):
    """JRX-02: a human pick-up with no wallet in the body binds LOGISTICS_DEFAULT_COURIER_WALLET -- and records the human, not 'system'."""
    monkeypatch.setattr(_main, "LOGISTICS_DEFAULT_COURIER_WALLET", WALLET_B)
    _orders_client_stub.notify_courier_assigned.reset_mock()
    s = _dispatched_shipment()
    client, db = _client(s)

    resp = client.put("/shipments/1/status", json={"status": "in_transit"})

    assert resp.status_code == 200, resp.text
    assert s.courier_id == "courier@postershop.com"
    assert s.courier_wallet == WALLET_B
    assert isinstance(s.courier_bound_at, datetime)

    body = resp.json()
    assert body["courier_id"] == "courier@postershop.com"
    assert body["courier_wallet"] == WALLET_B
    assert body["courier_bound_at"] == s.courier_bound_at.isoformat()

    db.commit.assert_called_once()
    _orders_client_stub.notify_courier_assigned.assert_awaited_once_with(784, WALLET_B)


def test_non_binding_transitions_record_nothing(monkeypatch):
    """JRX-02: only a pick-up that actually binds a wallet writes the three columns -- in_transit -> delivered (even with a wallet) and a pick-up with nothing to bind leave them null."""
    _orders_client_stub.notify_courier_assigned.reset_mock()

    # in_transit -> delivered: not a pick-up, a wallet in the body is ignored
    monkeypatch.setattr(_main, "LOGISTICS_DEFAULT_COURIER_WALLET", WALLET_B)
    s = _models.Shipment(id=1, order_id=784, status="in_transit", tracking="TRK-000784")
    client, db = _client(s)
    resp = client.put("/shipments/1/status", json={"status": "delivered", "courier_wallet": WALLET_A})
    assert resp.status_code == 200, resp.text
    assert s.status == "delivered"
    assert s.courier_id is None
    assert s.courier_wallet is None
    assert s.courier_bound_at is None
    body = resp.json()
    assert body["courier_id"] is None
    assert body["courier_wallet"] is None
    assert body["courier_bound_at"] is None
    db.commit.assert_called_once()

    # dispatched -> in_transit with no explicit wallet and no default: nothing to bind
    monkeypatch.setattr(_main, "LOGISTICS_DEFAULT_COURIER_WALLET", None)
    s = _dispatched_shipment()
    client, db = _client(s)
    resp = client.put("/shipments/1/status", json={"status": "in_transit"})
    assert resp.status_code == 200, resp.text
    assert s.status == "in_transit"
    assert s.courier_id is None
    assert s.courier_wallet is None
    assert s.courier_bound_at is None
    body = resp.json()
    assert body["courier_id"] is None
    assert body["courier_wallet"] is None
    assert body["courier_bound_at"] is None
    db.commit.assert_called_once()

    _orders_client_stub.notify_courier_assigned.assert_not_awaited()
