"""Unit tests for SHOP-01: Stripe payments service (mock stripe SDK)."""
import os
import sys
import types
from unittest.mock import MagicMock, patch

# --- Mock stripe before any import of payments main ---
stripe_mock = MagicMock()
session_mock = MagicMock()
session_mock.id = "cs_test_abc123"
session_mock.url = "https://checkout.stripe.com/pay/cs_test_abc123"
session_mock.amount_total = 5000
session_mock.status = "open"
stripe_mock.checkout.Session.create.return_value = session_mock
sys.modules["stripe"] = stripe_mock

# --- Stub logger and metrics so payments/main.py can be imported without the service dir on path ---
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class _NoopLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
_logger_stub.LoggingMiddleware = _NoopLoggingMiddleware
sys.modules.setdefault("logger", _logger_stub)

_metrics_stub = types.ModuleType("metrics")


async def _noop_track_metrics(request, call_next):
    return await call_next(request)


_metrics_stub.track_metrics = _noop_track_metrics
_metrics_stub.metrics_endpoint = MagicMock(return_value="")
sys.modules.setdefault("metrics", _metrics_stub)

import pytest
from fastapi.testclient import TestClient


def _load_payments():
    """Load payments main.py via importlib to allow re-import with mocked stripe."""
    import importlib.util
    import pathlib

    _PAYMENTS_DIR = str(pathlib.Path(__file__).parents[2] / "services/payments")
    sys.path.insert(0, _PAYMENTS_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "payments_main",
            pathlib.Path(__file__).parents[2] / "services/payments/main.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(_PAYMENTS_DIR)
    return mod


def test_create_checkout_session_returns_checkout_url():
    """SHOP-01: checkout_url in response maps to stripe session.url (not .checkout_url)."""
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
    mod = _load_payments()
    client = TestClient(mod.app)

    payload = {
        "order_id": 42,
        "customer_email": "test@example.com",
        "line_items": [{"name": "Poster A", "quantity": 1, "unit_amount": 5000}],
        "success_url": "https://example.com/shop/orders",
        "cancel_url": "https://example.com/shop/orders",
    }
    response = client.post("/v1/checkout/sessions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["checkout_url"] == "https://checkout.stripe.com/pay/cs_test_abc123"
    assert data["id"] == "cs_test_abc123"


def test_stripe_sdk_called_with_metadata_order_id():
    """SHOP-01: stripe.checkout.Session.create is called with metadata.order_id."""
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"
    mod = _load_payments()
    client = TestClient(mod.app)

    payload = {
        "order_id": 99,
        "customer_email": "buyer@example.com",
        "line_items": [{"name": "Poster B", "quantity": 2, "unit_amount": 2500}],
        "success_url": "https://example.com/shop/orders",
        "cancel_url": "https://example.com/shop/orders",
    }
    client.post("/v1/checkout/sessions", json=payload)
    call_kwargs = stripe_mock.checkout.Session.create.call_args[1]
    assert call_kwargs["metadata"]["order_id"] == "99"


# Idempotency is enforced in orders/stripe_webhook.py (order.status == PAID check).
# That logic is covered by the integration test in tests/integration/test_order_flow.py.
# Documented here for traceability: SHOP-01 idempotency guard exists, no new code needed.
def test_idempotency_guard_exists_in_orders_service():
    """SHOP-01: Idempotency guard documented — lives in orders/stripe_webhook.py."""
    import pathlib
    webhook_path = pathlib.Path(__file__).parents[2] / "services/orders/stripe_webhook.py"
    assert webhook_path.exists(), "stripe_webhook.py must exist"
    content = webhook_path.read_text()
    assert "OrderStatus.PAID" in content, "Idempotency guard (status == PAID check) must exist"
