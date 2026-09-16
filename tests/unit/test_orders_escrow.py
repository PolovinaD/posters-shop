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

    def _check(self, name):
        self.calls.append(name)
        if self.fail_with is not None:
            raise self.fail_with

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
finally:
    sys.path.remove(_ORDERS_DIR)
    for _mod_name in (
        "models", "escrow_rules", "order_paid",
        "schemas", "logger", "metrics", "database",
    ):
        sys.modules.pop(_mod_name, None)


OrderStatus = _ord_models.OrderStatus
is_wallet_address = _rules.is_wallet_address
decide_reconcile_action = _rules.decide_reconcile_action
mark_order_paid = _paid.mark_order_paid
InvalidPaidTransition = _paid.InvalidPaidTransition


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
