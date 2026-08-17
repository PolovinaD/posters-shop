"""
Unit tests for GAUGE-01..GAUGE-04: the orders_by_status Prometheus gauge.

What the bug was, and what these tests pin down:

  The prometheus_client library does not materialise a labelled child until
  `.labels(...)` is called on it for the first time. The gauge used to be written
  only inside the GET /orders/stats/by-status request handler, so on a pod that
  had never served that request the metric was ABSENT from /metrics -- not zero.
  Grafana renders an absent series as "No data", which is exactly what the
  Pending Orders / Paid Orders / Orders by Status Over Time panels showed on any
  cold pod.

  The interesting behaviour here is metric-shaped rather than DB-shaped, and
  metric shape is precisely what prometheus_client lets us assert:
  `registry.get_sample_value(...)` returns None for a child that does not exist
  and 0.0 for one that exists at zero. That is the literal difference between
  "No data" and "0".

Module isolation strategy:
  `metrics` is stubbed with a REAL prometheus_client Gauge built on a private
  CollectorRegistry. Loading the real services/orders/metrics.py would register
  http_requests_total in the global prometheus_client.REGISTRY, and
  test_inventory_reservation.py already loads the real inventory metrics.py --
  a second one in the same pytest session raises "Duplicated timeseries in
  CollectorRegistry" and aborts collection. A private registry gives us real
  prometheus semantics with zero global state.
"""
import asyncio
import importlib.util
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry, Gauge
from sqlalchemy.orm import DeclarativeBase

_ORDERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/orders")
)

# Private registry: real Gauge semantics, no global REGISTRY collision.
_TEST_REGISTRY = CollectorRegistry()

# A label value that neither init_orders_by_status() nor refresh_orders_by_status()
# ever writes, and that no test below touches. It stays absent for the whole
# session, so test_gauge_absent_before_init holds under -k selection and under
# any future test-ordering plugin.
_NEVER_WRITTEN_STATUS = "__never_written__"

_METRIC = "orders_by_status"


def _load_orders_module(name: str, alias: str):
    """Load a module from services/orders/ under a unique alias."""
    spec = importlib.util.spec_from_file_location(
        alias, os.path.join(_ORDERS_DIR, f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    spec.loader.exec_module(mod)
    return mod


def _sample(status: str):
    """Current value of orders_by_status{status=...}; None if the child does not exist."""
    return _TEST_REGISTRY.get_sample_value(_METRIC, {"status": status})


# ---------------------------------------------------------------------------
# Bootstrap: stub every dependency so status_metrics.py can be imported without
# a database, a network, or the global prometheus registry.
# ---------------------------------------------------------------------------

class _RealBase(DeclarativeBase):
    """Real declarative base -- models.Order must be genuinely mapped for
    select(Order.status).group_by(Order.status) to build."""


_db_stub = types.ModuleType("database")
_db_stub.Base = _RealBase
_db_stub.engine = MagicMock()
_db_stub.get_db = MagicMock()
_db_stub.SessionLocal = MagicMock()
# Unconditional assignment, NOT setdefault: a sibling test module may already
# occupy the "database" slot with its own Base. Torn down in the finally block.
sys.modules["database"] = _db_stub

sys.modules.setdefault("psycopg2", MagicMock())
sys.modules.setdefault("psycopg2.extras", MagicMock())

_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
sys.modules["logger"] = _logger_stub

_metrics_stub = types.ModuleType("metrics")
_metrics_stub.ORDERS_BY_STATUS = Gauge(
    _METRIC, "Current orders by status", ["status"], registry=_TEST_REGISTRY
)
sys.modules["metrics"] = _metrics_stub

sys.path.insert(0, _ORDERS_DIR)
try:
    _ord_models = _load_orders_module("models", alias="orders_gauge_models")
    sys.modules["models"] = _ord_models
    _status_metrics = _load_orders_module(
        "status_metrics", alias="orders_gauge_status_metrics"
    )
finally:
    sys.path.remove(_ORDERS_DIR)
    for _mod_name in ("models", "logger", "metrics", "database"):
        sys.modules.pop(_mod_name, None)

OrderStatus = _ord_models.OrderStatus

# Snapshot taken at import time -- BEFORE any test has run and therefore before
# any test could have called init_orders_by_status(). Importing the module must
# not by itself materialise anything, so every one of these must be None. This
# is order-proof: no test can retroactively change a value captured here.
_PRE_INIT_SAMPLES = {
    status: _sample(status) for status in _status_metrics.ALL_STATUSES
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_returning(rows):
    """Mock Session whose db.execute(...).all() yields the given (status, count) rows."""
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gauge_absent_before_init():
    """GAUGE-02 premise: an un-written labelled child is ABSENT, not zero.

    This is the root cause in one assertion. Two independent pieces of evidence:
    the import-time snapshot (all eight statuses were None before any test ran),
    and a live label that nothing in this module ever writes.
    """
    assert len(_PRE_INIT_SAMPLES) == 8
    for status, value in _PRE_INIT_SAMPLES.items():
        assert value is None, (
            f"orders_by_status{{status={status!r}}} existed at import time; the "
            f"'absent, not zero' premise no longer holds"
        )

    assert _sample(_NEVER_WRITTEN_STATUS) is None, (
        "a never-labelled child must read None -- this is what Grafana shows as 'No data'"
    )


def test_init_creates_all_eight_statuses_at_zero():
    """GAUGE-02: after init, every status exists at 0.0. This is 'No data' -> '0'."""
    _status_metrics.init_orders_by_status()

    expected = {
        OrderStatus.CREATED, OrderStatus.RESERVED, OrderStatus.PAID,
        OrderStatus.PRODUCING, OrderStatus.SHIPPED, OrderStatus.DELIVERED,
        OrderStatus.CANCELLED, OrderStatus.FAILED,
    }
    assert set(_status_metrics.ALL_STATUSES) == expected
    assert len(_status_metrics.ALL_STATUSES) == 8

    for status in expected:
        assert _sample(status) == 0.0, (
            f"orders_by_status{{status={status!r}}} is {_sample(status)!r}; "
            f"init must publish 0.0, not leave the child absent"
        )


def test_compute_returns_only_db_present_statuses():
    """GAUGE-03: compute is the API's shape -- no zero-fill on the response path.

    GET /orders/stats/by-status must return exactly the body it returned before
    this change: only the statuses the GROUP BY actually produced.
    """
    db = _db_returning([("delivered", 6), ("cancelled", 1)])

    stats = _status_metrics.compute_orders_by_status(db)

    assert stats == {"delivered": 6, "cancelled": 1}
    assert _status_metrics.compute_orders_by_status(_db_returning([])) == {}


def test_refresh_publishes_counts_and_zeros():
    """GAUGE-01: refresh publishes the DB counts AND zero-fills the rest."""
    db = _db_returning([("delivered", 6), ("cancelled", 1)])

    _status_metrics.refresh_orders_by_status(db)

    assert _sample(OrderStatus.DELIVERED) == 6.0
    assert _sample(OrderStatus.CANCELLED) == 1.0
    assert _sample(OrderStatus.CREATED) == 0.0, (
        "a status with no rows must be published as 0.0, not left absent"
    )


def test_refresh_clears_status_that_emptied():
    """GAUGE-01: a status that empties out must fall to 0, not freeze at its last value.

    Fails against an implementation that only writes the statuses the query
    returned -- the stale value would then live on this pod forever.
    """
    _status_metrics.refresh_orders_by_status(_db_returning([("paid", 3)]))
    assert _sample(OrderStatus.PAID) == 3.0

    _status_metrics.refresh_orders_by_status(_db_returning([]))
    assert _sample(OrderStatus.PAID) == 0.0, (
        "paid kept a stale value after the query stopped returning it"
    )


def test_worker_survives_db_error():
    """GAUGE-04: a transient DB failure logs and retries; it does not kill the worker.

    A worker that dies on the first RDS blip is worse than the bug being fixed,
    because the gauge then freezes at a stale value that still looks plausible.

    Drive with asyncio.run -- there is no pytest-asyncio in tests/requirements.txt.
    The fake sleep both removes the real 15s wait and terminates the otherwise
    infinite loop, so CancelledError propagating out is proof that the loop was
    still alive after three consecutive DB failures.
    """
    sleep_calls = []

    async def _fake_sleep(delay):
        sleep_calls.append(delay)
        if len(sleep_calls) >= 3:
            raise asyncio.CancelledError
        return None

    failing_session_local = MagicMock(side_effect=RuntimeError("connection refused"))

    with patch.object(_status_metrics, "SessionLocal", failing_session_local), \
         patch.object(_status_metrics.asyncio, "sleep", _fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(_status_metrics.orders_by_status_worker(refresh_interval=0.0))

    assert len(sleep_calls) == 3, (
        f"worker reached sleep {len(sleep_calls)} time(s); it must survive every "
        f"DB error and keep looping"
    )
    assert failing_session_local.call_count == 3
    assert _status_metrics.logger.error.call_count == 3, (
        "each DB failure must be logged via the structured logger"
    )
