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


def courier_binding_wallet(old_status: str, new_status: str, courier_wallet: str | None, default_wallet: str | None) -> str | None:
    """Wallet to bind to the order's escrow contract on THIS transition, or None.

    Only the pick-up (dispatched -> in_transit) binds a courier — that is when a
    real person takes the parcel. An explicit wallet (the courier's profile, sent
    by the dashboard) wins; LOGISTICS_DEFAULT_COURIER_WALLET covers the
    unattended worker; neither set -> None, and the order simply has no courier
    to bind.
    """
    if old_status != "dispatched" or new_status != "in_transit":
        return None
    return courier_wallet or default_wallet or None


def courier_id_from_claims(claims: dict | None) -> str | None:
    """Identity to record as the courier who bound a wallet, or None for "system".

    `sub` is the caller's user identity -- users mints the email into it -- so a
    human token records it as-is. A service token carries `service:<name>` and is
    not a person: it records None, the same value the unattended worker records.
    A missing or empty `sub` records None rather than guessing.
    """
    sub = (claims or {}).get("sub")
    if not isinstance(sub, str) or not sub or sub.startswith("service:"):
        return None
    return sub
