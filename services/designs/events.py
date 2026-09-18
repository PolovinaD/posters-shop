"""ORDER_PAID consumer (D-07). Fast, idempotent, DB-only: the outbox gives us 10 s and
retries the WHOLE event (to production and notifications too) on any non-2xx, so never
call a provider here and never 5xx for an unknown SKU.

Per item: an own variant SKU (AI-{id}-{size}, printing.generation_id_from_sku) stamps
`purchased_at` on that generation once; every item — own or an ordinary poster — becomes
a `purchases` row so the style profile can name what the customer bought. The profile is
then marked stale and the event id recorded in `processed_events` (notifications
precedent), so a re-delivery answers `already_processed` without touching anything.
"""
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from logger import get_logger
from models import Generation, ProcessedEvent, Purchase
from printing import generation_id_from_sku
from schemas import OutboxEventPayload
from style_profile import mark_stale

logger = get_logger(__name__)

DEDUP_SQL = text("SELECT 1 FROM designs_schema.processed_events WHERE event_id = :id")


def process_order_paid(db, event: OutboxEventPayload, now: datetime | None = None) -> dict:
    """Apply one ORDER_PAID event and commit. Returns the JSON the route answers with."""
    now = now or datetime.now(timezone.utc)
    if db.execute(DEDUP_SQL, {"id": event.event_id}).first():
        logger.info("Event already processed (idempotent)", event_id=event.event_id)
        return {"status": "already_processed", "event_id": event.event_id}

    payload = event.payload or {}
    email = payload.get("customer_email")
    if not email:
        # Nothing to attribute and nothing to retry — do NOT 500 (the outbox would re-deliver forever).
        logger.warning("ORDER_PAID without customer_email, skipping", event_id=event.event_id)
        return {"status": "skipped", "reason": "no_customer_email", "event_id": event.event_id}

    order_id = int(payload.get("order_id") or 0)
    own, bought = 0, 0
    for item in payload.get("items") or []:
        sku = str(item.get("sku") or "")
        name = str(item.get("name") or item.get("sku") or "")
        if not sku:
            continue
        gid = generation_id_from_sku(sku)
        if gid is not None:
            gen = db.get(Generation, gid)
            if gen is not None:
                if gen.purchased_at is None:
                    gen.purchased_at = now
                own += 1
        db.add(Purchase(customer_email=email, order_id=order_id, sku=sku, name=name, purchased_at=now))
        bought += 1

    mark_stale(db, email)
    db.execute(_record(event))
    try:
        db.commit()
    except IntegrityError as e:
        # A previous delivery crashed between the purchases insert and the processed_events
        # insert: the (order_id, sku) rows already exist, so the re-delivery trips the unique
        # constraint. The purchases and the purchased_at stamp are already durable from that
        # first attempt — roll back and record the event alone so the outbox stops retrying.
        logger.warning(
            "ORDER_PAID purchases already recorded; recording the event only",
            event_id=event.event_id, order_id=order_id, error=str(e.orig or e),
        )
        db.rollback()
        db.execute(_record(event))
        db.commit()

    logger.info(
        "ORDER_PAID processed",
        event_id=event.event_id, order_id=order_id, customer=email, own_designs=own, purchases=bought,
    )
    return {"status": "processed", "event_id": event.event_id, "own_designs": own, "purchases": bought}


def _record(event: OutboxEventPayload):
    """INSERT ... ON CONFLICT DO NOTHING on processed_events: a concurrent re-delivery must
    not error on the primary key."""
    return (
        pg_insert(ProcessedEvent)
        .values(event_id=event.event_id, event_type="ORDER_PAID")
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
