"""
Unit tests for ESC-03 / ESC-07: the orders side of the Ethereum escrow payment.

Section 1 - pure rules (escrow_rules) and the extracted mark_order_paid.
Section 2 - the escrow endpoints, internal courier binding and cancel refund
            against a FakeEscrow payment_client that walks the contract's
            state machine.
Section 3 - the reconciler worker.

Module isolation strategy mirrors tests/unit/test_order_cancel.py: every
orders dependency (database, schemas, logger, metrics, clients, outbox,
circuit_breaker, stripe_webhook) is stubbed in sys.modules, then models /
escrow_rules / order_paid / main are loaded from services/orders under unique
aliases. email_validator is not installed, so the real schemas.py is never
imported here. No chain, no network, no database.
"""
import asyncio
import importlib.util
import os
import sys
import types
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

_ORDERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/orders")
)

OWNER = "0x" + "aa" * 20
CUSTOMER = "0x" + "11" * 20
COURIER = "0x" + "22" * 20


def _load_orders_module(name: str, alias: str):
    """Load a module from services/orders/ under a unique alias."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(_ORDERS_DIR, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Bootstrap: stub every dependency so the orders modules import without I/O.
# ---------------------------------------------------------------------------

from sqlalchemy.orm import DeclarativeBase  # noqa: E402


class _RealBase(DeclarativeBase):
    pass


_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()
sys.modules["database"] = _db_stub

sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())


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
    customer_email: str
    items: list[_OrderItemCreate]
    payment_method: str = "stripe"
    customer_wallet: str | None = None


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
    payment_method: str = "stripe"
    escrow_status: str | None = None


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


class _NoopLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
_logger_stub.LoggingMiddleware = _NoopLoggingMiddleware
sys.modules["logger"] = _logger_stub


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

_inv_stub = types.ModuleType("inventory_client")
_inv_stub.release_stock = AsyncMock(return_value={"released_count": 1})
_inv_stub.commit_stock = AsyncMock(return_value={"committed_count": 1})
_inv_stub.InsufficientStockError = type("InsufficientStockError", (Exception,), {})
_inv_stub.SkuNotFoundError = type("SkuNotFoundError", (Exception,), {})
_inv_stub.InventoryServiceError = type("InventoryServiceError", (Exception,), {})
sys.modules["inventory_client"] = _inv_stub

_cat_stub = types.ModuleType("catalog_client")
_cat_stub.resolve_prices = AsyncMock(return_value={})
_cat_stub.CatalogError = type("CatalogError", (Exception,), {})
_cat_stub.CatalogServiceError = type("CatalogServiceError", (Exception,), {})
_cat_stub.UnknownSkuError = type("UnknownSkuError", (Exception,), {})
sys.modules["catalog_client"] = _cat_stub

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


# --- payment_client stub: exception classes + FakeEscrow state machine -------

class PaymentServiceError(Exception):
    pass


class EscrowRejectedError(PaymentServiceError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class EscrowUnavailableError(PaymentServiceError):
    pass


class EscrowContractMissingError(PaymentServiceError):
    pass


class FakeEscrow:
    """In-memory OrderEscrow: one contract per address, CONTRACT A shapes."""

    def __init__(self):
        self.contracts = {}
        self.calls = []
        self.fail_with = None  # exception instance raised by every call when set
        self.fail_on = {}      # {method name: exception instance} raised by that call only

    def _check(self, name):
        self.calls.append(name)
        if self.fail_with is not None:
            raise self.fail_with
        if name in self.fail_on:
            raise self.fail_on[name]

    def fund(self, address):
        assert self.contracts[address]["state"] == "awaiting_payment"
        self.contracts[address]["state"] = "funded"

    async def create_escrow(self, order_id, customer_address, amount_usd):
        self._check("create_escrow")
        address = "0x" + f"{order_id:040x}"
        amount_wei = str(int(Decimal(amount_usd) * 10**15))
        self.contracts[address] = {
            "state": "awaiting_payment",
            "owner": OWNER,
            "customer": customer_address,
            "courier": None,
            "price_wei": amount_wei,
            "balance_wei": "0",
        }
        return {
            "contract_address": address,
            "deploy_tx_hash": "0x" + "aa" * 32,
            "amount_wei": amount_wei,
        }

    async def get_escrow_state(self, address):
        self._check("get_escrow_state")
        if address not in self.contracts:
            raise EscrowContractMissingError("no contract at address")
        return dict(self.contracts[address])

    async def get_escrow_invoice(self, address):
        self._check("get_escrow_invoice")
        if address not in self.contracts:
            raise EscrowContractMissingError("no contract at address")
        return {
            "to": address,
            "value": self.contracts[address]["price_wei"],
            "data": "0x1b9265b8",
            "chain_id": 1337,
        }

    async def get_escrow_config(self):
        self._check("get_escrow_config")
        return {
            "enabled": True,
            "chain_id": 1337,
            "rpc_url": "/rpc",
            "wei_per_usd": 10**15,
            "courier_share_bps": 2000,
            "owner_address": OWNER,
        }

    async def assign_escrow_courier(self, address, courier_address):
        self._check("assign_escrow_courier")
        c = self.contracts.get(address)
        if c is None:
            raise EscrowContractMissingError("no contract at address")
        if c["state"] in ("released", "cancelled"):
            raise EscrowRejectedError("Order closed.")
        if c["state"] != "funded":
            raise EscrowRejectedError("Transfer not complete.")
        c["state"] = "in_delivery"
        c["courier"] = courier_address
        return {"tx_hash": "0x" + "bb" * 32, "state": "in_delivery"}

    async def release_escrow(self, address):
        self._check("release_escrow")
        c = self.contracts.get(address)
        if c is None:
            raise EscrowContractMissingError("no contract at address")
        if c["state"] in ("released", "cancelled"):
            raise EscrowRejectedError("Order closed.")
        if c["state"] != "in_delivery":
            raise EscrowRejectedError("Delivery not complete.")
        c["state"] = "released"
        return {"tx_hash": "0x" + "cc" * 32, "state": "released"}

    async def cancel_escrow(self, address):
        self._check("cancel_escrow")
        c = self.contracts.get(address)
        if c is None:
            raise EscrowContractMissingError("no contract at address")
        if c["state"] in ("released", "cancelled"):
            raise EscrowRejectedError("Order closed.")
        if c["state"] not in ("awaiting_payment", "funded"):
            raise EscrowRejectedError("Cannot cancel.")
        c["state"] = "cancelled"
        return {"tx_hash": "0x" + "dd" * 32, "state": "cancelled"}


fake = FakeEscrow()

_pay_stub = types.ModuleType("payment_client")
_pay_stub.PaymentServiceError = PaymentServiceError
_pay_stub.EscrowRejectedError = EscrowRejectedError
_pay_stub.EscrowUnavailableError = EscrowUnavailableError
_pay_stub.EscrowContractMissingError = EscrowContractMissingError
_pay_stub.create_checkout_session = AsyncMock()
_pay_stub.get_session_status = AsyncMock()
for _fn in (
    "create_escrow", "get_escrow_state", "get_escrow_invoice", "get_escrow_config",
    "assign_escrow_courier", "release_escrow", "cancel_escrow",
):
    # Bound at call time so a test may swap `fake` methods (e.g. to raise).
    setattr(_pay_stub, _fn, (lambda name: (lambda *a, **k: getattr(fake, name)(*a, **k)))(_fn))
sys.modules["payment_client"] = _pay_stub


# --- Load the production modules under aliases --------------------------------

sys.path.insert(0, _ORDERS_DIR)
try:
    _ord_models = _load_orders_module("models", alias="orders_escrow_models")
    sys.modules["models"] = _ord_models
    _rules = _load_orders_module("escrow_rules", alias="orders_escrow_rules")
    sys.modules["escrow_rules"] = _rules
    _paid = _load_orders_module("order_paid", alias="orders_escrow_paid")
    sys.modules["order_paid"] = _paid
    _reconciler = _load_orders_module("escrow_reconciler", alias="orders_escrow_reconciler")
    sys.modules["escrow_reconciler"] = _reconciler
    # main.py is loaded LAST so it binds the very module objects above.
    _ord_main = _load_orders_module("main", alias="orders_main_escrow_test")
finally:
    sys.path.remove(_ORDERS_DIR)
    for _mod_name in (
        "models", "escrow_rules", "order_paid", "escrow_reconciler",
        "schemas", "logger", "metrics", "database",
    ):
        sys.modules.pop(_mod_name, None)


OrderStatus = _ord_models.OrderStatus
reconcile_once = _reconciler.reconcile_once
open_escrow_orders_query = _reconciler.open_escrow_orders_query
is_wallet_address = _rules.is_wallet_address
decide_reconcile_action = _rules.decide_reconcile_action
mark_order_paid = _paid.mark_order_paid
InvalidPaidTransition = _paid.InvalidPaidTransition

_CUSTOMER_CLAIMS = {"sub": "test@example.com", "role": "customer"}
_SERVICE_CLAIMS = {"sub": "service:logistics", "role": "service"}


def _customer_claims():
    return _CUSTOMER_CLAIMS


def _service_claims():
    return _SERVICE_CLAIMS


def _client_with_db(override_get_db):
    """TestClient with get_db, get_current_user_claims and require_service_or_owner overridden."""
    from fastapi.testclient import TestClient

    _ord_main.app.dependency_overrides[_db_stub.get_db] = override_get_db
    _ord_main.app.dependency_overrides[_ord_main.get_current_user_claims] = _customer_claims
    _ord_main.app.dependency_overrides[_ord_main.require_service_or_owner] = _service_claims
    return TestClient(_ord_main.app, raise_server_exceptions=False)


def _client_for(order):
    """TestClient whose db.get returns `order` (None -> not found). Returns (client, db)."""
    db = MagicMock()
    db.get.return_value = order

    def override_get_db():
        yield db

    return _client_with_db(override_get_db), db


def _escrow_order(status="reserved", payment_method="escrow", order_id=1):
    order = MagicMock()
    order.id = order_id
    order.status = status
    order.customer_email = "test@example.com"
    order.total_amount = Decimal("12.50")
    order.items = []
    order.checkout_session_id = None
    order.payment_intent_id = None
    order.payment_method = payment_method
    order.customer_wallet = CUSTOMER if payment_method == "escrow" else None
    order.courier_wallet = None
    order.escrow_contract_address = None
    order.escrow_deploy_tx = None
    order.escrow_amount_wei = None
    order.escrow_status = "awaiting_payment" if payment_method == "escrow" else None
    return order


def _deploy(client, order):
    """POST /orders/{id}/escrow and return the contract address."""
    r = client.post(f"/orders/{order.id}/escrow")
    assert r.status_code == 200, r.text
    return r.json()["contract_address"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(sku, name, quantity):
    i = MagicMock()
    i.sku = sku
    i.name = name
    i.quantity = quantity
    return i


def _paid_order(status="reserved"):
    order = MagicMock()
    order.id = 7
    order.status = status
    order.customer_email = "test@example.com"
    order.total_amount = Decimal("12.50")
    order.payment_intent_id = None
    order.items = [_item("SKU-1", "Poster A", 2), _item("SKU-2", "Poster B", 1)]
    return order


@pytest.fixture(autouse=True)
def _reset_stubs():
    _outbox_stub.emit_event.reset_mock()
    _inv_stub.commit_stock = AsyncMock(return_value={"committed_count": 1})
    fake.contracts.clear()
    fake.calls.clear()
    fake.fail_with = None
    fake.fail_on = {}
    yield


# ---------------------------------------------------------------------------
# Section 1: pure rules + mark_order_paid
# ---------------------------------------------------------------------------

def test_wallet_regex():
    assert is_wallet_address("0x" + "ab" * 20) is True
    assert is_wallet_address("0x" + "AB" * 20) is True
    for bad in ("0x123", "", None, "0x" + "ab" * 19, "0x" + "gg" * 20, " 0x" + "ab" * 20):
        assert is_wallet_address(bad) is False, bad


@pytest.mark.parametrize("order_status,escrow_status,courier,chain,expected", [
    ("reserved", "awaiting_payment", None, "funded", "mark_paid"),
    ("reserved", "awaiting_payment", None, "in_delivery", "mark_paid"),
    ("reserved", "awaiting_payment", None, "awaiting_payment", "noop"),
    ("paid", "funded", COURIER, "funded", "bind_courier"),
    ("shipped", "funded", COURIER, "funded", "bind_courier"),
    ("paid", "funded", None, "funded", "noop"),
    ("paid", "funded", COURIER, "in_delivery", "sync_in_delivery"),
    ("delivered", "released", None, "released", "noop"),
    ("cancelled", "awaiting_payment", None, "funded", "refund"),
    ("cancelled", "funded", None, "funded", "refund"),
    ("failed", "awaiting_payment", None, "awaiting_payment", "refund"),
    ("cancelled", "funded", None, "in_delivery", "noop"),
    ("cancelled", "cancelled", None, "cancelled", "noop"),
    ("reserved", "awaiting_payment", None, None, "mark_failed"),
    ("paid", "funded", COURIER, None, "mark_failed"),
])
def test_reconcile_decisions(order_status, escrow_status, courier, chain, expected):
    assert decide_reconcile_action(order_status, escrow_status, courier, chain) == expected


def test_mark_order_paid_commits_stock_sets_paid_and_emits_event():
    db = MagicMock()
    order = _paid_order("reserved")

    assert asyncio.run(mark_order_paid(db, order, payment_ref="0xabc")) is True

    assert order.status == "paid"
    assert order.payment_intent_id == "0xabc"
    _inv_stub.commit_stock.assert_awaited_once_with(order.id)
    _outbox_stub.emit_event.assert_called_once()
    kwargs = _outbox_stub.emit_event.call_args.kwargs
    assert kwargs["event_type"] == "ORDER_PAID"
    assert kwargs["payload"]["order_id"] == order.id
    assert kwargs["payload"]["payment_intent"] == "0xabc"
    assert kwargs["payload"]["items"] == [
        {"sku": "SKU-1", "name": "Poster A", "quantity": 2},
        {"sku": "SKU-2", "name": "Poster B", "quantity": 1},
    ]
    db.commit.assert_called_once()


def test_mark_order_paid_is_idempotent():
    db = MagicMock()
    order = _paid_order("paid")

    assert asyncio.run(mark_order_paid(db, order, payment_ref="0xabc")) is False

    _outbox_stub.emit_event.assert_not_called()
    db.commit.assert_not_called()


def test_mark_order_paid_rejects_invalid_transition():
    db = MagicMock()
    order = _paid_order("producing")
    with pytest.raises(InvalidPaidTransition):
        asyncio.run(mark_order_paid(db, order, payment_ref="0xabc"))
    _outbox_stub.emit_event.assert_not_called()


def test_mark_order_paid_survives_inventory_failure():
    db = MagicMock()
    order = _paid_order("reserved")
    _inv_stub.commit_stock = AsyncMock(side_effect=Exception("down"))

    assert asyncio.run(mark_order_paid(db, order, payment_ref="0xabc")) is True
    assert order.status == "paid"
    _outbox_stub.emit_event.assert_called_once()


# ---------------------------------------------------------------------------
# Section 2: endpoints against the FakeEscrow payment_client
# ---------------------------------------------------------------------------

def test_escrow_deploy_stores_contract_and_is_idempotent():
    order = _escrow_order()
    client, db = _client_for(order)

    r = client.post("/orders/1/escrow")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"order_id", "contract_address", "deploy_tx_hash", "amount_wei", "invoice", "config"}
    assert order.escrow_contract_address == body["contract_address"]
    assert order.escrow_amount_wei == "12500000000000000"
    assert body["amount_wei"] == "12500000000000000"
    assert order.escrow_status == "awaiting_payment"
    assert body["invoice"]["to"] == body["contract_address"]
    assert body["config"]["chain_id"] == 1337
    db.commit.assert_called()

    r2 = client.post("/orders/1/escrow")
    assert r2.status_code == 200, r2.text
    assert r2.json()["contract_address"] == body["contract_address"]
    assert fake.calls.count("create_escrow") == 1


def test_escrow_deploy_rejects_stripe_order():
    order = _escrow_order(payment_method="stripe")
    client, _ = _client_for(order)
    r = client.post("/orders/1/escrow")
    assert r.status_code == 400
    assert "not an escrow order" in r.json()["detail"]


def test_escrow_deploy_requires_reserved():
    order = _escrow_order(status="paid")
    client, _ = _client_for(order)
    r = client.post("/orders/1/escrow")
    assert r.status_code == 400
    assert "reserved" in r.json()["detail"]
    assert "create_escrow" not in fake.calls


def test_escrow_deploy_503_when_payments_down():
    order = _escrow_order()
    client, _ = _client_for(order)

    fake.fail_with = EscrowUnavailableError("down")
    r = client.post("/orders/1/escrow")
    assert r.status_code == 503, r.text
    assert order.escrow_contract_address is None

    fake.fail_with = _cb_stub.CircuitOpenError("open")
    r = client.post("/orders/1/escrow")
    assert r.status_code == 503, r.text


def test_verify_marks_paid_when_funded():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)

    r = client.post("/orders/1/escrow/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "paid"
    assert body["chain_state"] == "funded"
    assert order.status == "paid"
    assert order.escrow_status == "funded"
    assert _outbox_stub.emit_event.call_count == 1
    assert _outbox_stub.emit_event.call_args.kwargs["event_type"] == "ORDER_PAID"
    assert _outbox_stub.emit_event.call_args.kwargs["payload"]["payment_intent"] == addr

    r2 = client.post("/orders/1/escrow/verify")
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "already_paid"
    assert _outbox_stub.emit_event.call_count == 1


def test_verify_reports_awaiting_when_not_funded():
    order = _escrow_order()
    client, _ = _client_for(order)
    _deploy(client, order)

    r = client.post("/orders/1/escrow/verify")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_payment"
    assert r.json()["chain_state"] == "awaiting_payment"
    assert order.status == "reserved"
    _outbox_stub.emit_event.assert_not_called()


def test_verify_without_contract_is_400():
    order = _escrow_order()
    client, _ = _client_for(order)
    r = client.post("/orders/1/escrow/verify")
    assert r.status_code == 400
    assert "not deployed" in r.json()["detail"]


def test_get_escrow_returns_stored_and_chain():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)

    r = client.get("/orders/1/escrow")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["escrow_status"] == "awaiting_payment"
    assert body["contract_address"] == addr
    assert body["amount_wei"] == "12500000000000000"
    assert body["customer_wallet"] == CUSTOMER
    assert body["courier_wallet"] is None
    assert body["chain"]["state"] == "awaiting_payment"
    assert body["chain_error"] is None

    fake.fail_with = EscrowUnavailableError("down")
    r = client.get("/orders/1/escrow")
    assert r.status_code == 200, r.text
    assert r.json()["chain"] is None
    assert r.json()["chain_error"]


def test_confirm_delivery_requires_delivered():
    order = _escrow_order(status="shipped")
    order.escrow_contract_address = "0x" + "01" * 20
    order.escrow_status = "in_delivery"
    client, _ = _client_for(order)
    r = client.post("/orders/1/escrow/confirm-delivery")
    assert r.status_code == 400
    assert "delivered" in r.json()["detail"]
    assert "release_escrow" not in fake.calls


def test_confirm_delivery_without_courier_is_409():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    order.status = "delivered"
    order.escrow_status = "funded"

    r = client.post("/orders/1/escrow/confirm-delivery")
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "Delivery not complete."
    assert order.escrow_status == "funded"


def test_confirm_delivery_releases():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    asyncio.run(fake.assign_escrow_courier(addr, COURIER))
    order.status = "delivered"
    order.escrow_status = "in_delivery"
    order.courier_wallet = COURIER

    r = client.post("/orders/1/escrow/confirm-delivery")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["order_id"] == 1
    assert body["escrow_status"] == "released"
    assert body["tx_hash"]
    assert order.escrow_status == "released"
    assert fake.contracts[addr]["state"] == "released"

    r2 = client.post("/orders/1/escrow/confirm-delivery")
    assert r2.status_code == 200, r2.text
    assert r2.json()["escrow_status"] == "released"
    assert r2.json()["status"] == "already_released"
    assert fake.calls.count("release_escrow") == 1


def test_internal_courier_binds_when_funded():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    order.status = "paid"
    order.escrow_status = "funded"

    r = client.post("/internal/orders/1/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "bound"
    assert r.json()["escrow_status"] == "in_delivery"
    assert r.json()["order_id"] == 1
    assert order.courier_wallet == COURIER
    assert order.escrow_status == "in_delivery"
    assert fake.contracts[addr]["courier"] == COURIER


def test_internal_courier_defers_when_not_funded_or_down():
    # 1. deployed but not funded -> deferred, wallet stored
    order = _escrow_order()
    client, _ = _client_for(order)
    _deploy(client, order)
    r = client.post("/internal/orders/1/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deferred"
    assert order.courier_wallet == COURIER
    assert order.escrow_status == "awaiting_payment"

    # 2. funded but payments down -> deferred
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    order.escrow_status = "funded"
    fake.fail_with = EscrowUnavailableError("down")
    r = client.post("/internal/orders/1/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deferred"
    assert order.courier_wallet == COURIER
    assert order.escrow_status == "funded"
    fake.fail_with = None

    # 3. stripe order -> stored
    order = _escrow_order(payment_method="stripe")
    client, _ = _client_for(order)
    r = client.post("/internal/orders/1/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "stored"
    assert order.courier_wallet == COURIER

    # 4. already in delivery -> already_bound
    order = _escrow_order()
    order.escrow_contract_address = "0x" + "01" * 20
    order.escrow_status = "in_delivery"
    client, _ = _client_for(order)
    r = client.post("/internal/orders/1/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "already_bound"

    # 5. unknown order -> not_found
    client, _ = _client_for(None)
    r = client.post("/internal/orders/999/courier", json={"courier_wallet": COURIER})
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "not_found", "order_id": 999, "escrow_status": None}

    # 6. malformed wallet -> 422
    order = _escrow_order()
    client, _ = _client_for(order)
    r = client.post("/internal/orders/1/courier", json={"courier_wallet": "0x123"})
    assert r.status_code == 422


def test_cancel_refunds_funded_escrow():
    order = _escrow_order()
    client, db = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    order.escrow_status = "funded"

    r = client.post("/orders/1/cancel")
    assert r.status_code == 200, r.text
    assert "cancel_escrow" in fake.calls
    assert fake.contracts[addr]["state"] == "cancelled"
    assert order.escrow_status == "cancelled"
    assert order.status == "cancelled"
    kwargs = _outbox_stub.emit_event.call_args.kwargs
    assert kwargs["event_type"] == "ORDER_CANCELLED"
    assert kwargs["payload"]["escrow_refunded"] is True


def test_cancel_refuses_when_refund_impossible():
    order = _escrow_order()
    client, _ = _client_for(order)
    addr = _deploy(client, order)
    fake.fund(addr)
    order.escrow_status = "funded"
    fake.fail_with = EscrowUnavailableError("down")

    r = client.post("/orders/1/cancel")
    assert r.status_code == 503, r.text
    assert order.status == "reserved"
    assert order.escrow_status == "funded"
    _outbox_stub.emit_event.assert_not_called()


def test_cancel_stripe_order_untouched():
    order = _escrow_order(payment_method="stripe")
    client, _ = _client_for(order)
    r = client.post("/orders/1/cancel")
    assert r.status_code == 200, r.text
    assert "cancel_escrow" not in fake.calls
    assert _outbox_stub.emit_event.call_args.kwargs["payload"]["escrow_refunded"] is False


def test_checkout_rejects_escrow_order():
    order = _escrow_order()
    client, _ = _client_for(order)
    r = client.post("/orders/1/checkout")
    assert r.status_code == 400, r.text
    assert "escrow" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Section 3: the reconciler
# ---------------------------------------------------------------------------

def _reconcile_db(*orders):
    db = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = list(orders)
    return db


def _chain_order(status, escrow_status, courier_wallet=None, order_id=1):
    """An escrow order whose contract exists in the fake (awaiting_payment)."""
    order = _escrow_order(status=status, order_id=order_id)
    deployed = asyncio.run(fake.create_escrow(order_id, CUSTOMER, "12.50"))
    order.escrow_contract_address = deployed["contract_address"]
    order.escrow_amount_wei = deployed["amount_wei"]
    order.escrow_status = escrow_status
    order.courier_wallet = courier_wallet
    return order


def _counts(**overrides):
    base = {"mark_paid": 0, "bind_courier": 0, "sync_in_delivery": 0, "refund": 0, "mark_failed": 0, "noop": 0}
    base.update(overrides)
    return base


def test_reconcile_once_marks_paid_when_chain_funded():
    order = _chain_order("reserved", "awaiting_payment")
    fake.fund(order.escrow_contract_address)
    db = _reconcile_db(order)

    counts = asyncio.run(reconcile_once(db))

    assert counts == _counts(mark_paid=1)
    assert order.status == "paid"
    assert order.escrow_status == "funded"
    _outbox_stub.emit_event.assert_called_once()
    assert _outbox_stub.emit_event.call_args.kwargs["event_type"] == "ORDER_PAID"
    db.commit.assert_called()


def test_reconcile_once_binds_deferred_courier():
    order = _chain_order("paid", "funded", courier_wallet=COURIER)
    fake.fund(order.escrow_contract_address)
    db = _reconcile_db(order)

    counts = asyncio.run(reconcile_once(db))

    assert counts == _counts(bind_courier=1)
    assert "assign_escrow_courier" in fake.calls
    assert order.escrow_status == "in_delivery"
    assert fake.contracts[order.escrow_contract_address]["courier"] == COURIER
    db.commit.assert_called()


def test_reconcile_once_marks_failed_when_contract_missing():
    order = _escrow_order(status="reserved")
    order.escrow_contract_address = "0x" + "ff" * 20  # never deployed in the fake
    db = _reconcile_db(order)

    counts = asyncio.run(reconcile_once(db))

    assert counts == _counts(mark_failed=1)
    assert order.escrow_status == "failed"
    assert order.status == "reserved"
    db.commit.assert_called()


def test_reconcile_once_survives_payments_outage():
    order = _chain_order("reserved", "awaiting_payment")
    fake.fund(order.escrow_contract_address)
    fake.fail_with = EscrowUnavailableError("down")
    db = _reconcile_db(order)

    counts = asyncio.run(reconcile_once(db))

    assert counts == _counts(noop=1)
    assert order.status == "reserved"
    assert order.escrow_status == "awaiting_payment"
    _outbox_stub.emit_event.assert_not_called()
    db.commit.assert_not_called()


def test_reconcile_once_refunds_cancelled_order():
    order = _chain_order("cancelled", "funded")
    fake.fund(order.escrow_contract_address)
    db = _reconcile_db(order)

    counts = asyncio.run(reconcile_once(db))

    assert counts == _counts(refund=1)
    assert "cancel_escrow" in fake.calls
    assert fake.contracts[order.escrow_contract_address]["state"] == "cancelled"
    assert order.escrow_status == "cancelled"
    assert order.status == "cancelled"
    db.commit.assert_called()

    # Variant: the contract refuses -> counted, logged, nothing mutated, no raise
    fake.calls.clear()
    order2 = _chain_order("cancelled", "funded", order_id=2)
    fake.fund(order2.escrow_contract_address)
    fake.fail_on = {"cancel_escrow": EscrowRejectedError("Cannot cancel.")}
    db2 = _reconcile_db(order2)

    counts = asyncio.run(reconcile_once(db2))

    assert counts == _counts(refund=1)
    assert "cancel_escrow" in fake.calls
    assert order2.escrow_status == "funded"
    db2.commit.assert_not_called()


def test_reconciler_query_targets_open_escrow_orders():
    rendered = str(open_escrow_orders_query())
    assert "orders_schema.orders.escrow_contract_address IS NOT NULL" in rendered
    assert "escrow_status IN" in rendered
    assert "orders_schema.orders.payment_method =" in rendered
