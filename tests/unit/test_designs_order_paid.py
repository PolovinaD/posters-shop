"""ORDER_PAID consumer (D-07, 09-05): services/designs/events.py on a MagicMock session
and the guarded POST /events/order-paid route with TestClient.

The handler must be fast, DB-only and idempotent for the outbox (10 s budget, whole-event
retry on any non-2xx): own variant SKUs stamp `purchased_at`, every item lands in
`purchases`, the profile goes stale, the event id is recorded, and a re-delivery answers
`already_processed` without touching anything."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=3)
OWN_ITEM = {"sku": "AI-7-A3", "name": "Custom: mountains (A3)", "quantity": 1}
FOREIGN_ITEM = {"sku": "POSTER-001-A2", "name": "Forest Mist (A2)", "quantity": 2}


@pytest.fixture(scope="module")
def d():
    return load_designs()


@pytest.fixture(scope="module")
def ev(d):
    return d.events


@pytest.fixture(scope="module")
def models(d):
    return d.models


def _event(d, payload, event_id=99):
    return d.schemas.OutboxEventPayload(
        event_id=event_id, event_type="ORDER_PAID", aggregate_type="order", aggregate_id="12", payload=payload,
    )


def _payload(items, email="c@x.io", order_id=12):
    p = {"order_id": order_id, "total_amount": "29.99", "payment_intent": None, "items": items}
    if email is not None:
        p["customer_email"] = email
    return p


def _session(models, seen=False, gen="default", profile=None):
    """A MagicMock session: `.execute(...).first()` answers the dedup lookup; `.get` answers
    the own-generation and the style-profile lookups by model."""
    s = MagicMock()
    s.execute.return_value.first.return_value = (1,) if seen else None
    if gen == "default":
        gen = SimpleNamespace(id=7, purchased_at=None)

    def get(model, key):
        if model is models.Generation:
            return gen
        if model is models.StyleProfile:
            return profile
        return None

    s.get.side_effect = get
    return s, gen


def _added(session, model):
    return [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], model)]


def _generation_lookups(session, models):
    return [c for c in session.get.call_args_list if c.args and c.args[0] is models.Generation]


def _executed_sql(session):
    out = []
    for c in session.execute.call_args_list:
        stmt = c.args[0]
        try:
            out.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
        except Exception:
            out.append(str(stmt))
    return out


# ---------------------------------------------------------------------------
# process_order_paid
# ---------------------------------------------------------------------------

def test_own_sku_sets_purchased_at_and_records_purchase(d, ev, models):
    session, gen = _session(models)
    result = ev.process_order_paid(session, _event(d, _payload([OWN_ITEM])), now=NOW)

    assert result == {"status": "processed", "event_id": 99, "own_designs": 1, "purchases": 1}
    assert gen.purchased_at == NOW
    purchases = _added(session, models.Purchase)
    assert len(purchases) == 1
    p = purchases[0]
    assert (p.customer_email, p.order_id, p.sku, p.name, p.purchased_at) == (
        "c@x.io", 12, "AI-7-A3", "Custom: mountains (A3)", NOW,
    )
    session.commit.assert_called_once()
    # the event is recorded through an INSERT ... ON CONFLICT DO NOTHING on processed_events
    sql = "\n".join(_executed_sql(session))
    assert "INSERT INTO designs_schema.processed_events" in sql
    assert "ON CONFLICT (event_id) DO NOTHING" in sql
    assert "'ORDER_PAID'" in sql


def test_foreign_sku_only_records_purchase(d, ev, models):
    session, _ = _session(models)
    result = ev.process_order_paid(session, _event(d, _payload([FOREIGN_ITEM])), now=NOW)

    assert result["own_designs"] == 0
    assert result["purchases"] == 1
    assert _generation_lookups(session, models) == []
    p = _added(session, models.Purchase)[0]
    assert (p.sku, p.name) == ("POSTER-001-A2", "Forest Mist (A2)")


def test_own_sku_already_purchased_not_overwritten(d, ev, models):
    session, gen = _session(models, gen=SimpleNamespace(id=7, purchased_at=EARLIER))
    result = ev.process_order_paid(session, _event(d, _payload([OWN_ITEM])), now=NOW)

    assert gen.purchased_at == EARLIER
    assert result["own_designs"] == 1
    assert result["purchases"] == 1


def test_unknown_generation_id_is_not_an_error(d, ev, models):
    session, _ = _session(models, gen=None)
    item = {"sku": "AI-424242-A1", "name": "Custom: gone (A1)", "quantity": 1}
    result = ev.process_order_paid(session, _event(d, _payload([item])), now=NOW)

    assert result["status"] == "processed"
    assert result["own_designs"] == 0
    assert result["purchases"] == 1
    assert len(_generation_lookups(session, models)) == 1  # it was looked up, and simply missing
    assert _added(session, models.Purchase)[0].sku == "AI-424242-A1"


def test_duplicate_event_is_already_processed(d, ev, models):
    session, gen = _session(models, seen=True)
    result = ev.process_order_paid(session, _event(d, _payload([OWN_ITEM])), now=NOW)

    assert result == {"status": "already_processed", "event_id": 99}
    session.add.assert_not_called()
    session.commit.assert_not_called()
    assert gen.purchased_at is None
    assert session.execute.call_count == 1  # only the dedup lookup ran


def test_empty_items_or_no_email_is_skipped_200(d, ev, models):
    session, _ = _session(models)
    result = ev.process_order_paid(session, _event(d, _payload([OWN_ITEM], email=None)), now=NOW)
    assert result == {"status": "skipped", "reason": "no_customer_email", "event_id": 99}
    session.add.assert_not_called()
    session.commit.assert_not_called()

    session, _ = _session(models)
    result = ev.process_order_paid(session, _event(d, _payload([])), now=NOW)
    assert result == {"status": "processed", "event_id": 99, "own_designs": 0, "purchases": 0}
    assert _added(session, models.Purchase) == []
    # still recorded, so the outbox never re-delivers an empty order
    assert "INSERT INTO designs_schema.processed_events" in "\n".join(_executed_sql(session))
    session.commit.assert_called_once()


def test_profile_marked_stale(d, ev, models):
    # no profile yet -> a fresh stale row is added
    session, _ = _session(models)
    ev.process_order_paid(session, _event(d, _payload([OWN_ITEM])), now=NOW)
    profiles = _added(session, models.StyleProfile)
    assert len(profiles) == 1
    assert profiles[0].customer_email == "c@x.io"
    assert profiles[0].stale is True

    # an existing fresh profile -> flipped to stale in place, nothing added
    prof = SimpleNamespace(customer_email="c@x.io", summary="old", stale=False)
    session, _ = _session(models, profile=prof)
    ev.process_order_paid(session, _event(d, _payload([FOREIGN_ITEM])), now=NOW)
    assert prof.stale is True
    assert _added(session, models.StyleProfile) == []


def test_integrity_error_on_purchases_still_records_event(d, ev, models):
    """A crash between the purchases insert and the processed_events insert on a previous
    delivery leaves the purchase rows behind; the re-delivery must not 5xx on the unique
    (order_id, sku) constraint but roll back and record the event alone."""
    session, gen = _session(models)
    session.commit.side_effect = [IntegrityError("INSERT INTO purchases", {}, Exception("uq_purchases_order_sku")), None]
    result = ev.process_order_paid(session, _event(d, _payload([OWN_ITEM])), now=NOW)

    assert result["status"] == "processed"
    session.rollback.assert_called_once()
    assert session.commit.call_count == 2
    inserts = [s for s in _executed_sql(session) if "INSERT INTO designs_schema.processed_events" in s]
    assert len(inserts) == 2  # once in the failed transaction, once alone after the rollback


# ---------------------------------------------------------------------------
# POST /events/order-paid
# ---------------------------------------------------------------------------

def test_route_guard_and_shape(d, models):
    main = d.main
    main.app.dependency_overrides.clear()
    client = TestClient(main.app)
    body = {
        "event_id": 99, "event_type": "ORDER_PAID", "aggregate_type": "order", "aggregate_id": "12",
        "payload": _payload([FOREIGN_ITEM]), "created_at": None,
    }
    assert client.post("/events/order-paid", json=body).status_code == 401

    session, _ = _session(models)
    main.app.dependency_overrides[main.get_db] = lambda: session
    main.app.dependency_overrides[main.require_service_or_owner] = lambda: {"sub": "service:orders", "role": "service"}
    try:
        r = client.post("/events/order-paid", json=body)
        assert r.status_code == 200
        assert r.json() == {"status": "processed", "event_id": 99, "own_designs": 0, "purchases": 1}
        session.commit.assert_called_once()
    finally:
        main.app.dependency_overrides.clear()
