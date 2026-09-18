"""Per-user daily generation quota (D-14).

Counts the customer's rows created since UTC midnight whose status is not 'failed':
a refusal or a provider outage is not the customer's fault, so failed rows do not
consume the allowance. The owner is exempt (demo convenience) and AI_DAILY_QUOTA=0
disables the limit. Over quota -> 429 with Retry-After counting down to UTC midnight
(the frontend's fetchJSON surfaces the header).
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from models import Generation


def utc_day_start(now: datetime | None = None) -> datetime:
    """Midnight UTC of the day containing `now` (default: the current instant)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until_utc_midnight(now: datetime | None = None) -> int:
    """Whole seconds until the next UTC midnight; never below 1 (a valid Retry-After)."""
    now = now or datetime.now(timezone.utc)
    remaining = utc_day_start(now) + timedelta(days=1) - now.astimezone(timezone.utc)
    return max(1, int(remaining.total_seconds()))


def count_accepted_today(db, customer_email: str, now: datetime | None = None) -> int:
    """Rows this customer created today that are not failed (queued/generating/ready)."""
    stmt = (
        select(func.count())
        .select_from(Generation)
        .where(
            Generation.customer_email == customer_email,
            Generation.status != "failed",
            Generation.created_at >= utc_day_start(now),
        )
    )
    return int(db.execute(stmt).scalar() or 0)


def check_quota(db, customer_email: str, role: str | None, limit: int, now: datetime | None = None) -> int:
    """Return today's accepted count; raise 429 (+ Retry-After to UTC midnight) when
    count >= limit. The owner is exempt and limit <= 0 means unlimited — both skip
    the query entirely."""
    if role == "owner" or limit <= 0:
        return 0
    used = count_accepted_today(db, customer_email, now)
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit of {limit} generations reached",
            headers={"Retry-After": str(seconds_until_utc_midnight(now))},
        )
    return used


def quota_status(db, customer_email: str, role: str | None, limit: int, now: datetime | None = None) -> dict:
    """The /me/quota payload: limit, used, remaining (None when exempt), resets_at, exempt."""
    exempt = role == "owner" or limit <= 0
    used = 0 if exempt else count_accepted_today(db, customer_email, now)
    return {
        "limit": limit,
        "used": used,
        "remaining": None if exempt else max(0, limit - used),
        "resets_at": utc_day_start(now) + timedelta(days=1),
        "exempt": exempt,
    }
