"""
Unit tests for OrderStatus state machine.
Tests: all 11 valid transitions, invalid transitions (skip-state, terminal-state),
can_cancel() truth table, and the thesis-notable PRODUCING -> CANCELLED block.
"""
import sys
import os
import types
import pytest

# Insert the orders service directory so we can import models directly
_ORDERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/orders")
)
sys.path.insert(0, _ORDERS_DIR)

# Stub the `database` module so SQLAlchemy engine creation is skipped.
# models.py imports `from database import Base` at module level, which triggers
# create_engine() with DATABASE_URL=None when no DB is running.
# OrderStatus is a pure Python class with no DB dependency; Base is only needed
# for the ORM models (Order, OrderItem) which we don't test here.
_db_stub = types.ModuleType("database")


class _StubBase:
    pass


_db_stub.Base = _StubBase
# Unconditional assignment, NOT setdefault: another test module may have left a
# real DeclarativeBase in the "database" slot whose MetaData already registered
# orders_schema.orders, and re-importing models.py against it raises
# InvalidRequestError. This file always gets its own lightweight _StubBase.
sys.modules["database"] = _db_stub

try:
    from models import OrderStatus
finally:
    # Leave sys.path and sys.modules exactly as we found them so this file
    # cannot influence whatever pytest collects next. OrderStatus is already
    # bound as a module global by now, so popping "models" is safe.
    sys.path.remove(_ORDERS_DIR)
    for _mod_name in ("models", "database"):
        sys.modules.pop(_mod_name, None)


# ---------------------------------------------------------------------------
# Valid transitions (all 11)
# ---------------------------------------------------------------------------
VALID_TRANSITIONS = [
    (OrderStatus.CREATED, OrderStatus.RESERVED),
    (OrderStatus.CREATED, OrderStatus.CANCELLED),
    (OrderStatus.CREATED, OrderStatus.FAILED),
    (OrderStatus.RESERVED, OrderStatus.PAID),
    (OrderStatus.RESERVED, OrderStatus.CANCELLED),
    (OrderStatus.RESERVED, OrderStatus.FAILED),
    (OrderStatus.PAID, OrderStatus.PRODUCING),
    (OrderStatus.PAID, OrderStatus.CANCELLED),
    (OrderStatus.PRODUCING, OrderStatus.SHIPPED),
    (OrderStatus.PRODUCING, OrderStatus.FAILED),
    (OrderStatus.SHIPPED, OrderStatus.DELIVERED),
]

@pytest.mark.parametrize("from_s,to_s", VALID_TRANSITIONS)
def test_valid_transitions(from_s, to_s):
    assert OrderStatus.can_transition(from_s, to_s), (
        f"Expected {from_s} -> {to_s} to be valid"
    )


# ---------------------------------------------------------------------------
# Invalid transitions (skip-state, reverse, and terminal-state)
# ---------------------------------------------------------------------------
INVALID_TRANSITIONS = [
    (OrderStatus.CREATED, OrderStatus.PAID),          # skip RESERVED
    (OrderStatus.CREATED, OrderStatus.PRODUCING),     # skip multiple
    (OrderStatus.RESERVED, OrderStatus.SHIPPED),      # skip PAID + PRODUCING
    (OrderStatus.PAID, OrderStatus.SHIPPED),          # skip PRODUCING
    (OrderStatus.DELIVERED, OrderStatus.CREATED),     # terminal -> anything
    (OrderStatus.DELIVERED, OrderStatus.SHIPPED),
    (OrderStatus.CANCELLED, OrderStatus.CREATED),     # terminal -> anything
    (OrderStatus.CANCELLED, OrderStatus.RESERVED),
    (OrderStatus.FAILED, OrderStatus.CREATED),        # terminal -> anything
    (OrderStatus.FAILED, OrderStatus.PRODUCING),
]

@pytest.mark.parametrize("from_s,to_s", INVALID_TRANSITIONS)
def test_invalid_transitions(from_s, to_s):
    assert not OrderStatus.can_transition(from_s, to_s), (
        f"Expected {from_s} -> {to_s} to be invalid"
    )


def test_terminal_states_have_no_outgoing_transitions():
    """Terminal states have empty TRANSITIONS entries."""
    for terminal in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.FAILED):
        assert OrderStatus.TRANSITIONS[terminal] == [], (
            f"Terminal state {terminal} should have no outgoing transitions"
        )


# ---------------------------------------------------------------------------
# Thesis-notable: PRODUCING cannot be cancelled
# ---------------------------------------------------------------------------
def test_producing_cannot_be_cancelled():
    """
    Once an order is in PRODUCING, it cannot be cancelled.
    This is an explicit business rule: the production floor has already started.
    """
    assert not OrderStatus.can_transition(OrderStatus.PRODUCING, OrderStatus.CANCELLED), (
        "PRODUCING -> CANCELLED must be blocked (production already started)"
    )
    assert not OrderStatus.can_cancel(OrderStatus.PRODUCING), (
        "can_cancel(PRODUCING) must return False"
    )


# ---------------------------------------------------------------------------
# can_cancel truth table
# ---------------------------------------------------------------------------
CAN_CANCEL_TRUE = [OrderStatus.CREATED, OrderStatus.RESERVED, OrderStatus.PAID]
CAN_CANCEL_FALSE = [
    OrderStatus.PRODUCING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.FAILED,
]

@pytest.mark.parametrize("status", CAN_CANCEL_TRUE)
def test_can_cancel_returns_true(status):
    assert OrderStatus.can_cancel(status), f"can_cancel({status}) should be True"


@pytest.mark.parametrize("status", CAN_CANCEL_FALSE)
def test_can_cancel_returns_false(status):
    assert not OrderStatus.can_cancel(status), f"can_cancel({status}) should be False"
