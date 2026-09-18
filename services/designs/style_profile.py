"""Style profile (D-07 tier 2 / D-16): a short summary of the customer's taste built from
their prompts and purchases.

Refreshed lazily — never inside the ORDER_PAID handler (10 s outbox budget) — by the
worker when 'Personalise' is on and the profile is stale, or on demand from the studio
page. Named style_profile (not profile) because `profile` is a stdlib module and the
uvicorn/pytest path order must never decide which one wins.
"""
from models import StyleProfile


def mark_stale(db, email: str) -> None:
    """Flag the customer's profile for a lazy refresh; a customer without a profile gets
    a stale placeholder row so the next personalised generation builds one."""
    prof = db.get(StyleProfile, email)
    if prof is None:
        db.add(StyleProfile(customer_email=email, stale=True))
    else:
        prof.stale = True
