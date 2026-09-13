"""Pure decision rules for the logistics shipment worker.

Deliberately free of SQLAlchemy, logging and asyncio. `database.py` builds its
engine at module scope from DATABASE_URL, so anything importing it — models.py
included — is unimportable without a database; keeping the auto-advance rule
here is what lets the unit test import the real production function instead of
restating it.
"""
from datetime import datetime, timezone


def next_status(status: str, updated_at: datetime, now: datetime, interval: float) -> str | None:
    """Status a shipment should advance to, or None if it is not yet due.

    `updated_at` comes back naive from the DB (no tzinfo), so UTC is attached
    before subtracting; `now` is expected to be timezone-aware.

    Only "dispatched" and "in_transit" ever reach here — shipment_worker's query
    filters on exactly those two — so any non-"dispatched" status advances to
    "delivered". That mirrors the ternary this was extracted from.
    """
    age = (now - updated_at.replace(tzinfo=timezone.utc)).total_seconds()
    if age < interval:
        return None
    return "in_transit" if status == "dispatched" else "delivered"
