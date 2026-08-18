"""
orders_by_status gauge ownership.

WHY this module exists:

1. A gauge that describes global database state must not be a request-path side
   effect. The count of orders per status is a property of the orders table, not
   of "whoever happened to call GET /orders/stats/by-status last". While the
   write lived in that handler, the value a pod published depended on whether
   that pod had served the request -- and orders runs behind a Service with 2+
   replicas, so one request warms one pod and the scrape targets disagree.

2. prometheus_client does not materialise a labelled child until `.labels(...)`
   is called on it. An un-initialised gauge is therefore ABSENT from /metrics,
   not zero, and Grafana renders an absent series as "No data". That is why the
   Pending Orders, Paid Orders and Orders by Status Over Time panels went blank
   on every restart, redeploy and scale-up. init_orders_by_status() pre-creates
   all eight labels at 0 so /metrics is complete from the very first scrape,
   even before the database has been read -- or if it cannot be reached at all.

3. Every replica refreshes, because every replica is scraped separately. N pods
   then publish N copies of the same global fact, so the dashboards and the
   alert aggregate with `max by (status)` -- never `sum`, which would multiply
   the count by the replica count.

See .planning/quick/260817-orders-status-gauge/ for the full rationale.
"""
import asyncio

from sqlalchemy import select, func as sql_func
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Order, OrderStatus
from metrics import ORDERS_BY_STATUS
from logger import get_logger

logger = get_logger("orders_status_metrics")

# Prometheus scrapes every 15s; matching that cadence means no scrape ever reads
# a value more than one refresh old (worst case ~30s end-to-end staleness).
# The query is a GROUP BY over an indexed column (ix_orders_status) on a table
# holding tens of rows: 8 queries/min at 2 replicas, 20/min at the HPA ceiling
# of 5, each borrowing a pooled connection for microseconds. See the PLAN.
REFRESH_INTERVAL_SECONDS = 15.0

# The eight states of the order state machine. Every one of them is published on
# every refresh -- see refresh_orders_by_status().
ALL_STATUSES = (
    OrderStatus.CREATED,
    OrderStatus.RESERVED,
    OrderStatus.PAID,
    OrderStatus.PRODUCING,
    OrderStatus.SHIPPED,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.FAILED,
)


def init_orders_by_status() -> None:
    """Materialise all eight labelled children at 0, without touching the database.

    Called at startup BEFORE the worker so /metrics is complete from the first
    scrape even if the database is unreachable -- the panels then read 0 rather
    than 'No data'.
    """
    for status_val in ALL_STATUSES:
        ORDERS_BY_STATUS.labels(status=status_val).set(0)


def compute_orders_by_status(db: Session) -> dict[str, int]:
    """GROUP BY status. Returns ONLY the statuses present in the database.

    The single owner of this query: the endpoint returns this verbatim and the
    worker zero-fills on top of it. Do not zero-fill here -- the API response
    shape must not change (an empty table still yields {}).
    """
    result = db.execute(
        select(Order.status, sql_func.count(Order.id))
        .group_by(Order.status)
    ).all()

    return {status: count for status, count in result}


def refresh_orders_by_status(db: Session) -> dict[str, int]:
    """Recompute and publish all eight labels, zero-filling the absent ones.

    Writing every status -- not just those the query returned -- is what stops a
    status that empties out from freezing at its last non-zero value on this pod.
    """
    stats = compute_orders_by_status(db)

    for status_val in ALL_STATUSES:
        ORDERS_BY_STATUS.labels(status=status_val).set(stats.get(status_val, 0))

    return stats


async def orders_by_status_worker(refresh_interval: float = REFRESH_INTERVAL_SECONDS):
    """Recompute the gauge on a timer. One instance per replica, by design.

    Work-then-sleep, so the first refresh lands at startup rather than one
    interval later. A transient database error is logged and swallowed: a worker
    that dies on the first RDS blip is worse than no worker at all, because the
    gauge then freezes at a stale value that still looks plausible.

    Args:
        refresh_interval: How often to recompute the gauge (seconds)
    """
    logger.info("Worker started", refresh_interval=refresh_interval)

    while True:
        try:
            with SessionLocal() as db:
                refresh_orders_by_status(db)
        except Exception as e:
            logger.error("Orders-by-status refresh failed", error=str(e), exc_info=True)

        await asyncio.sleep(refresh_interval)
