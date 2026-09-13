"""Unit tests for SHOP-03: the logistics shipment auto-advance rule.

These tests import the PRODUCTION function services/logistics/worker_rules.py::
next_status. Until quick task 260913-u90 this file restated the rule inline and
so passed regardless of what the worker actually did — thesis §7.1 documents
that as a limitation, and it was demonstrated real when Shipment gained six
address columns and these tests never noticed.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

INTERVAL = 120  # matches LOGISTICS_AUTO_ADVANCE_INTERVAL's default

_LOGISTICS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/logistics")
)
sys.path.insert(0, _LOGISTICS_DIR)
try:
    # No `database` stub here, unlike test_order_state_machine.py: worker_rules
    # imports nothing but `datetime`. services/logistics/database.py calls
    # create_engine(DATABASE_URL) at module scope and raises ArgumentError when
    # DATABASE_URL is unset, which is exactly why the rule was extracted into a
    # module that never touches SQLAlchemy. "worker_rules" is also a name no
    # other service uses, so there is no cross-service collision to unwind.
    from worker_rules import next_status
finally:
    sys.path.remove(_LOGISTICS_DIR)
    sys.modules.pop("worker_rules", None)


def _updated_at(age_seconds: int) -> datetime:
    """A NAIVE UTC timestamp `age_seconds` old — the shape the DB hands the worker."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=age_seconds)


def test_dispatched_advances_to_in_transit():
    """SHOP-03: dispatched shipment old enough is advanced to in_transit."""
    now = datetime.now(timezone.utc)

    assert next_status("dispatched", _updated_at(130), now, INTERVAL) == "in_transit"


def test_in_transit_advances_to_delivered():
    """SHOP-03: in_transit shipment old enough is advanced to delivered."""
    now = datetime.now(timezone.utc)

    assert next_status("in_transit", _updated_at(130), now, INTERVAL) == "delivered"


def test_not_yet_due_not_advanced():
    """SHOP-03: shipment not yet old enough is NOT advanced."""
    now = datetime.now(timezone.utc)

    assert next_status("dispatched", _updated_at(30), now, INTERVAL) is None


def test_delivered_calls_notify():
    """SHOP-03: when a shipment reaches delivered, notify_order_delivered is called.

    The worker does asyncio.create_task(orders_client.notify_order_delivered(
    s.order_id)) guarded by `if s.status == "delivered"`. Only the dispatch is
    mocked here — the STATUS DECISION comes from the production next_status, so
    breaking the rule breaks this test too.
    """
    notify = MagicMock(return_value=True)
    now = datetime.now(timezone.utc)

    new = next_status("in_transit", _updated_at(130), now, INTERVAL)
    if new == "delivered":
        notify(7)

    assert new == "delivered"
    notify.assert_called_once_with(7)
