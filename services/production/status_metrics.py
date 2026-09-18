"""
jobs_by_status gauge ownership.

WHY this module exists — the same three reasons as orders/status_metrics.py,
because production carried an identical defect:

1. A gauge that describes global database state must not be a request-path side
   effect. The count of jobs per status is a property of the jobs table, not of
   "whoever happened to call GET /jobs/stats/summary last". While the write lived
   in that handler, the value a pod published depended on whether that pod had
   served the request -- and production scales to 5 replicas under its CPU HPA,
   so one request warms one pod and the scrape targets disagree.

2. prometheus_client does not materialise a labelled child until `.labels(...)`
   is called on it. An un-initialised gauge is therefore ABSENT from /metrics,
   not zero, and Grafana renders an absent series as "No data". init_jobs_by_status()
   pre-creates all four labels at 0 so /metrics is complete from the very first
   scrape, even before the database has been read -- or if it cannot be reached
   at all. (Contrast production_jobs_queued, which is UNLABELLED and so exists
   from module import; that difference is the whole bug.)

3. Every replica refreshes, because every replica is scraped separately. N pods
   then publish N copies of the same global fact, so any dashboard or alert must
   aggregate with `max by (status)` -- never `sum`, which would multiply the
   count by the replica count.

See services/orders/status_metrics.py for the original of this pattern.
"""
import asyncio

from sqlalchemy import select, func as sql_func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from database import SessionLocal
from models import Job, JobStatus
from metrics import JOBS_BY_STATUS
from logger import get_logger

logger = get_logger("production_status_metrics")

# Prometheus scrapes every 15s; matching that cadence means no scrape ever reads
# a value more than one refresh old. The query is a GROUP BY over an indexed
# column (ix_jobs_status) on a small table, borrowing a pooled connection for
# microseconds.
REFRESH_INTERVAL_SECONDS = 15.0

# The four states of the production job state machine. Every one of them is
# published on every refresh -- see refresh_jobs_by_status().
ALL_STATUSES = (
    JobStatus.QUEUED,
    JobStatus.PROCESSING,
    JobStatus.COMPLETED,
    JobStatus.FAILED,
)


def init_jobs_by_status() -> None:
    """Materialise all four labelled children at 0, without touching the database.

    Called at startup BEFORE the worker so /metrics is complete from the first
    scrape even if the database is unreachable -- panels then read 0 rather than
    'No data'.
    """
    for status_val in ALL_STATUSES:
        JOBS_BY_STATUS.labels(status=status_val).set(0)


def compute_jobs_by_status(db: Session) -> dict[str, int]:
    """GROUP BY status. Returns ONLY the statuses present in the database.

    The single owner of this query: the endpoint returns this verbatim and the
    worker zero-fills on top of it. Do not zero-fill here -- the API response
    shape must not change (an empty table still yields {}).
    """
    result = db.execute(
        select(Job.status, sql_func.count(Job.id))
        .group_by(Job.status)
    ).all()

    return {status: count for status, count in result}


def refresh_jobs_by_status(db: Session) -> dict[str, int]:
    """Recompute and publish all four labels, zero-filling the absent ones.

    Writing every status -- not just those the query returned -- is what stops a
    status that empties out from freezing at its last non-zero value on this pod.
    """
    stats = compute_jobs_by_status(db)

    for status_val in ALL_STATUSES:
        JOBS_BY_STATUS.labels(status=status_val).set(stats.get(status_val, 0))

    return stats


async def jobs_by_status_worker(refresh_interval: float = REFRESH_INTERVAL_SECONDS):
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
            await run_in_threadpool(_refresh_pass)
        except Exception as e:
            logger.error("Jobs-by-status refresh failed", error=str(e), exc_info=True)

        await asyncio.sleep(refresh_interval)


def _refresh_pass() -> dict[str, int]:
    """One synchronous refresh on a threadpool thread (SQL never runs on the
    event loop). SessionLocal is looked up at call time, module-global."""
    with SessionLocal() as db:
        return refresh_jobs_by_status(db)
