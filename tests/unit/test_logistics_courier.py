"""Unit tests for ESC-04: the logistics courier hand-off on pick-up.

Two production pieces are exercised without a database or network:

- services/logistics/worker_rules.py::courier_binding_wallet — the pure rule that
  decides which wallet (if any) a shipment transition binds to the order's
  escrow contract. Imported with the same sys.path recipe as
  test_logistics_worker.py (the module imports only `datetime`).
- services/logistics/orders_client.py::notify_courier_assigned — CONTRACT B's
  caller. Loaded under a unique alias with `service_auth` stubbed (the real one
  needs SERVICE_JWT config) and `httpx.AsyncClient` replaced by a fake that
  records the request, so the test pins the exact path and body orders (08-02)
  expects: POST /internal/orders/{id}/courier {"courier_wallet": ...}.
"""
import asyncio
import importlib.util
import os
import sys
import types

_LOGISTICS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/logistics")
)

WALLET_A = "0x" + "22" * 20
WALLET_B = "0x" + "33" * 20

sys.path.insert(0, _LOGISTICS_DIR)
try:
    from worker_rules import courier_binding_wallet
finally:
    sys.path.remove(_LOGISTICS_DIR)
    sys.modules.pop("worker_rules", None)


# ---------------------------------------------------------------------------
# courier_binding_wallet — pure rule
# ---------------------------------------------------------------------------

def test_courier_binding_wallet_matrix():
    """ESC-04: only dispatched -> in_transit binds; explicit wallet wins over the default; empty == unset."""
    cases = [
        (("dispatched", "in_transit", WALLET_A, WALLET_B), WALLET_A),   # explicit wins
        (("dispatched", "in_transit", None, WALLET_B), WALLET_B),       # default covers the worker
        (("dispatched", "in_transit", "", WALLET_B), WALLET_B),         # empty string == unset
        (("dispatched", "in_transit", None, None), None),               # nothing to bind
        (("dispatched", "in_transit", None, ""), None),                 # empty default == unset
        (("in_transit", "delivered", WALLET_A, WALLET_B), None),        # only pick-up binds
        (("dispatched", "dispatched", WALLET_A, None), None),           # no transition
        (("preparing", "in_transit", WALLET_A, None), None),            # not from dispatched
    ]
    for args, expected in cases:
        assert courier_binding_wallet(*args) == expected, f"courier_binding_wallet{args} != {expected!r}"


# ---------------------------------------------------------------------------
# notify_courier_assigned — CONTRACT B request shape
# ---------------------------------------------------------------------------

def _load_orders_client():
    """Load services/logistics/orders_client.py under a unique alias with service_auth stubbed.

    The stub is installed only for the duration of the load and the previous
    sys.modules entry (if any) is restored, so the payments tests — which import
    their own real service_auth — are unaffected by collection order.
    """
    os.environ["ORDERS_SERVICE_URL"] = "http://orders.test:8000"
    stub = types.ModuleType("service_auth")
    stub.internal_headers = lambda service_name=None: {"Authorization": "Bearer test"}
    previous = sys.modules.get("service_auth")
    sys.modules["service_auth"] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            "logistics_orders_client_test",
            os.path.join(_LOGISTICS_DIR, "orders_client.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["logistics_orders_client_test"] = mod
        spec.loader.exec_module(mod)
    finally:
        if previous is not None:
            sys.modules["service_auth"] = previous
        else:
            sys.modules.pop("service_auth", None)
    return mod


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient: records every post(url, json=...)."""
    calls = []
    status_code = 200
    text = '{"status":"bound"}'
    raise_exc = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, **kwargs):
        if _FakeAsyncClient.raise_exc is not None:
            raise _FakeAsyncClient.raise_exc
        _FakeAsyncClient.calls.append((url, json))
        return _FakeResponse(_FakeAsyncClient.status_code, _FakeAsyncClient.text)


def _reset_fake(status_code=200, text='{"status":"bound"}', raise_exc=None):
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.status_code = status_code
    _FakeAsyncClient.text = text
    _FakeAsyncClient.raise_exc = raise_exc


def test_notify_courier_assigned_posts_contract_b(monkeypatch):
    """ESC-04: pick-up posts CONTRACT B exactly — /internal/orders/{id}/courier with {"courier_wallet": ...}."""
    mod = _load_orders_client()
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)
    _reset_fake()

    ok = asyncio.run(mod.notify_courier_assigned(42, WALLET_A))

    assert ok is True
    assert _FakeAsyncClient.calls == [
        ("http://orders.test:8000/internal/orders/42/courier", {"courier_wallet": WALLET_A}),
    ]


def test_notify_courier_assigned_returns_false_on_non_200_and_exception(monkeypatch):
    """ESC-04: fire-and-forget — a 404 (orders side not shipped yet) or a transport error is swallowed as False."""
    mod = _load_orders_client()
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient)

    _reset_fake(status_code=404, text='{"detail":"Not Found"}')
    assert asyncio.run(mod.notify_courier_assigned(42, WALLET_A)) is False

    _reset_fake(raise_exc=RuntimeError("boom"))
    assert asyncio.run(mod.notify_courier_assigned(42, WALLET_A)) is False
