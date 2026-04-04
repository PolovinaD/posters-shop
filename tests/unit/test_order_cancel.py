"""
Unit tests for SHOP-02: orders cancel endpoint status validation.

Tests cancel_order endpoint HTTP behavior:
- 200 for CREATED/RESERVED/PAID orders
- 400 for PRODUCING/SHIPPED/DELIVERED/CANCELLED orders
- 404 for nonexistent orders

Module isolation strategy:
  All orders service dependencies (database, models, schemas, metrics, etc.) are
  stubbed at module level via sys.modules so loading orders/main.py does not
  require a real database or network connection.
"""
import sys
import os
import types
import importlib
import importlib.util
import pytest
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

_ORDERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/orders")
)


def _load_orders_module(name: str, alias: str = None):
    """Load a module from services/orders/ with a unique alias."""
    spec = importlib.util.spec_from_file_location(
        alias or f"orders_cancel_{name}",
        os.path.join(_ORDERS_DIR, f"{name}.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias or f"orders_cancel_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Bootstrap: stub all dependencies so orders/main.py can be imported.
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
sys.modules.setdefault("database", _db_stub)

# Ensure psycopg2 is stubbed
sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

# 2. Stub schemas with Pydantic models (avoids email-validator dependency for EmailStr)
class _OrderItemCreate(BaseModel):
    sku: str
    name: str
    quantity: int = 1
    unit_price: Decimal

class _OrderItemOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    sku: str
    name: str
    quantity: int
    unit_price: Decimal

class _OrderCreate(BaseModel):
    customer_email: str  # str instead of EmailStr to avoid email-validator
    items: list[_OrderItemCreate]

class _OrderOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    customer_email: str
    status: str
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    items: list[_OrderItemOut]

class _OrderSummary(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    customer_email: str
    status: str
    total_amount: Decimal
    created_at: datetime
    item_count: int

class _StatusTransition(BaseModel):
    new_status: str

class _CancelOrderResponse(BaseModel):
    order_id: int
    status: str
    released_stock: bool
    message: str

_schemas_stub = types.ModuleType("schemas")
_schemas_stub.OrderCreate = _OrderCreate
_schemas_stub.OrderOut = _OrderOut
_schemas_stub.OrderSummary = _OrderSummary
_schemas_stub.OrderItemOut = _OrderItemOut
_schemas_stub.StatusTransition = _StatusTransition
_schemas_stub.CancelOrderResponse = _CancelOrderResponse
sys.modules["schemas"] = _schemas_stub

# 3. Logger stub (avoids structured logger loading)
class _NoopLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)

_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
_logger_stub.LoggingMiddleware = _NoopLoggingMiddleware
sys.modules["logger"] = _logger_stub

# 4. Metrics stub
async def _noop_track_metrics(request, call_next):
    return await call_next(request)

_metrics_stub = types.ModuleType("metrics")
_metrics_stub.track_metrics = _noop_track_metrics
_metrics_stub.metrics_endpoint = MagicMock(return_value="")
_metrics_stub.ORDERS_CREATED = MagicMock()
_metrics_stub.ORDERS_BY_STATUS = MagicMock()
_metrics_stub.ORDER_TOTAL_AMOUNT = MagicMock()
_metrics_stub.INVENTORY_RESERVATION_FAILURES = MagicMock()
_metrics_stub.SERVICE_NAME = "orders"
sys.modules["metrics"] = _metrics_stub

# 5. Stub external service clients
_inv_stub = types.ModuleType("inventory_client")
_inv_stub.release_stock = AsyncMock(return_value={"released_count": 1})
_inv_stub.InsufficientStockError = type("InsufficientStockError", (Exception,), {})
_inv_stub.SkuNotFoundError = type("SkuNotFoundError", (Exception,), {})
_inv_stub.InventoryServiceError = type("InventoryServiceError", (Exception,), {})
sys.modules["inventory_client"] = _inv_stub

_pay_stub = types.ModuleType("payment_client")
_pay_stub.PaymentServiceError = type("PaymentServiceError", (Exception,), {})
sys.modules["payment_client"] = _pay_stub

_outbox_stub = types.ModuleType("outbox")
_outbox_stub.emit_event = MagicMock()
_outbox_stub.outbox_worker = AsyncMock()
_outbox_stub.get_pending_event_count = MagicMock(return_value=0)
_outbox_stub.get_failed_event_count = MagicMock(return_value=0)
_outbox_stub.OutboxEvent = MagicMock()
sys.modules["outbox"] = _outbox_stub

_cb_stub = types.ModuleType("circuit_breaker")
_cb_stub.CircuitOpenError = type("CircuitOpenError", (Exception,), {})
sys.modules["circuit_breaker"] = _cb_stub

_stripe_stub = types.ModuleType("stripe_webhook")
_stripe_stub.process_webhook = AsyncMock()
_stripe_stub.WebhookError = type("WebhookError", (Exception,), {})
sys.modules["stripe_webhook"] = _stripe_stub

# 6. Load orders/models.py so OrderStatus is available
sys.path.insert(0, _ORDERS_DIR)
try:
    _ord_models = _load_orders_module("models")
    sys.modules["models"] = _ord_models

    # 7. Load orders/main.py
    _ord_main = _load_orders_module("main", alias="orders_main_cancel_test")
finally:
    sys.path.remove(_ORDERS_DIR)
    # Remove generic aliases to avoid polluting other test files
    for _mod_name in ("models", "schemas", "logger", "metrics"):
        sys.modules.pop(_mod_name, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

OrderStatus = _ord_models.OrderStatus


def _make_order(status: str, order_id: int = 1):
    """Create a minimal mock Order object."""
    order = MagicMock()
    order.id = order_id
    order.status = status
    order.items = []
    order.customer_email = "test@example.com"
    order.total_amount = Decimal("100.00")
    return order


def _get_client_for_order(order):
    """Return TestClient with DB dependency overridden to return the given order."""
    from fastapi.testclient import TestClient

    def override_get_db():
        db = MagicMock()
        db.get.return_value = order
        yield db

    _ord_main.app.dependency_overrides[_db_stub.get_db] = override_get_db
    return TestClient(_ord_main.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests: cancellable statuses return 200
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["created", "reserved", "paid"])
def test_cancel_cancellable_order_returns_200(status):
    """SHOP-02: cancel endpoint returns 200 for CREATED/RESERVED/PAID orders."""
    order = _make_order(status)
    client = _get_client_for_order(order)
    response = client.post("/orders/1/cancel")
    assert response.status_code == 200, (
        f"Expected 200 for status={status}, got {response.status_code}: {response.text}"
    )


# ---------------------------------------------------------------------------
# Tests: non-cancellable statuses return 400
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["producing", "shipped", "delivered", "cancelled"])
def test_cancel_non_cancellable_order_returns_400(status):
    """SHOP-02: cancel endpoint returns 400 for PRODUCING/SHIPPED/DELIVERED/CANCELLED orders."""
    order = _make_order(status)
    client = _get_client_for_order(order)
    response = client.post("/orders/1/cancel")
    assert response.status_code == 400, (
        f"Expected 400 for status={status}, got {response.status_code}: {response.text}"
    )
    detail = response.json().get("detail", "")
    assert "cancel" in detail.lower() or "Cannot" in detail, (
        f"Expected 'cancel' or 'Cannot' in detail for status={status}, got: {detail}"
    )


# ---------------------------------------------------------------------------
# Test: nonexistent order returns 404
# ---------------------------------------------------------------------------

def test_cancel_nonexistent_order_returns_404():
    """SHOP-02: cancel endpoint returns 404 when order does not exist."""
    from fastapi.testclient import TestClient

    def override_get_db_none():
        db = MagicMock()
        db.get.return_value = None  # order not found
        yield db

    _ord_main.app.dependency_overrides[_db_stub.get_db] = override_get_db_none
    client = TestClient(_ord_main.app, raise_server_exceptions=False)
    response = client.post("/orders/999/cancel")
    assert response.status_code == 404
