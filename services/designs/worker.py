"""Background generation worker (D-02 / D-04 / D-05).

One loop per replica, started from main.py's lifespan. Each iteration:

  claim  -> one UPDATE ... FOR UPDATE SKIP LOCKED ... RETURNING flips the oldest
            due `queued` row to `generating` and bumps `attempts`; the session is
            committed and CLOSED before anything else happens
  call   -> the provider runs through the circuit breaker (seconds to minutes) with
            NO session and NO row lock held (pitfall 6: a pooled connection pinned
            for a minute per job would exhaust the pool)
  store  -> the PNG goes to the Storage backend in a thread (sync fs / boto3 call)
  persist-> a fresh, short-lived session writes the outcome

Error taxonomy -> outcome (outcome_for_error):
  PromptRejected      failed, the vendor's reason is user-visible, no retry
  ProviderConfigError failed, generic reason (our misconfiguration is not shown), no retry
  CircuitOpenError    stays queued until the breaker's recovery timeout; the attempt is
                      handed back (attempts - 1) because the provider was never called
  ProviderError / *   queued with backoff RETRY_BACKOFF[attempt - 1] (5 s, 30 s, ...)
                      until attempts >= DESIGNS_MAX_ATTEMPTS, then failed

Several replicas can run the loop: SKIP LOCKED makes the claim safe, and one job at
a time per replica is deliberate (the provider is the bottleneck, not the loop).
"""
import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text

from circuit_breaker import CircuitBreaker, CircuitOpenError
from database import SessionLocal
from logger import get_logger
from metrics import GENERATIONS_TOTAL, PROVIDER_LATENCY, QUEUE_DEPTH
from models import Generation
from providers import PromptRejected, ProviderConfigError, ProviderError, user_ref
from storage import new_image_key

logger = get_logger(__name__)

POLL_INTERVAL = float(os.getenv("DESIGNS_WORKER_POLL_INTERVAL", "1.0"))
MAX_ATTEMPTS = int(os.getenv("DESIGNS_MAX_ATTEMPTS", "3"))
RETRY_BACKOFF = [5, 30, 120]  # seconds to wait after attempt 1, 2, 3, ... (last value repeats)
CB_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
CB_RECOVERY_TIMEOUT = float(os.getenv("CB_RECOVERY_TIMEOUT", "30"))

CONFIG_ERROR_REASON = "The image provider is not configured correctly; please try again later"
UNAVAILABLE_REASON = "The image provider is unavailable right now; please try again later"

# One breaker per process in front of the image provider (D-04). PromptRejected and
# ProviderConfigError are business errors by name and never trip it (circuit_breaker.py).
provider_cb = CircuitBreaker(
    service="image_provider",
    failure_threshold=CB_FAILURE_THRESHOLD,
    recovery_timeout=CB_RECOVERY_TIMEOUT,
)

# Atomic claim: the subquery picks the oldest due row and skips rows another replica
# holds; the UPDATE flips it to generating and consumes an attempt in the same statement.
CLAIM_SQL = text("""
    UPDATE designs_schema.generations
       SET status = 'generating', started_at = now(), attempts = attempts + 1
     WHERE id = (SELECT id FROM designs_schema.generations
                  WHERE status = 'queued' AND (retry_after IS NULL OR retry_after <= now())
                  ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
 RETURNING id, customer_email, prompt, effective_prompt, personalise, attempts
""")


@dataclass
class Outcome:
    """What the worker writes back after one attempt."""
    status: str                              # ready | failed | queued
    image_key: Optional[str] = None
    failure_reason: Optional[str] = None
    retry_after: Optional[datetime] = None
    attempts: Optional[int] = None           # value to write back (None = keep the claimed value)


def claim_next(session_factory=SessionLocal) -> Optional[dict]:
    """Claim the oldest due queued row (status -> generating, attempts + 1) and return
    it as a plain dict, or None when the queue is empty. The session is closed on return."""
    with session_factory() as db:
        row = db.execute(CLAIM_SQL).mappings().first()
        db.commit()
    return dict(row) if row else None


def outcome_for_error(exc: Exception, attempts: int, now: datetime) -> Outcome:
    """Map a provider/breaker exception to the outcome to persist (see module docstring)."""
    if isinstance(exc, PromptRejected):
        return Outcome(status="failed", failure_reason=str(exc))
    if isinstance(exc, ProviderConfigError):
        return Outcome(status="failed", failure_reason=CONFIG_ERROR_REASON)
    if isinstance(exc, CircuitOpenError):
        # The provider was never called: hand the attempt back and wait for the probe window.
        return Outcome(
            status="queued",
            retry_after=now + timedelta(seconds=CB_RECOVERY_TIMEOUT),
            attempts=max(0, attempts - 1),
        )
    # ProviderError and anything unexpected: retry with backoff, then fail.
    if attempts >= MAX_ATTEMPTS:
        return Outcome(status="failed", failure_reason=UNAVAILABLE_REASON)
    delay = RETRY_BACKOFF[min(attempts, len(RETRY_BACKOFF)) - 1]
    return Outcome(status="queued", retry_after=now + timedelta(seconds=delay))


def apply_outcome(db, generation_id: int, outcome: Outcome, provider_name: str, params: dict, now: datetime) -> None:
    """Write one attempt's outcome onto the row and commit. A vanished row is a no-op."""
    gen = db.get(Generation, generation_id)
    if gen is None:
        return
    gen.status = outcome.status
    gen.provider = provider_name
    gen.params = params
    if outcome.status == "ready":
        gen.image_key = outcome.image_key
        gen.finished_at = now
        gen.failure_reason = None
    elif outcome.status == "failed":
        gen.failure_reason = outcome.failure_reason
        gen.finished_at = now
    else:
        gen.retry_after = outcome.retry_after
    if outcome.attempts is not None:
        gen.attempts = outcome.attempts
    db.commit()


async def run_generation(
    row: dict, *, provider, storage, breaker: CircuitBreaker = provider_cb,
    session_factory=SessionLocal, now: datetime | None = None,
) -> str:
    """Run one claimed row through provider -> storage -> outcome. Returns the final status.

    No session exists while the provider runs; the outcome is persisted through a fresh
    one. Storage writes are sync (filesystem or boto3) and run in a thread (pitfall 7)."""
    now = now or datetime.now(timezone.utc)
    gid, email, attempts = row["id"], row["customer_email"], int(row.get("attempts") or 1)
    prompt = row.get("effective_prompt") or row["prompt"]
    started = time.monotonic()
    try:
        png = await breaker.call(lambda: provider.generate(prompt, user_ref(email)))
        key = new_image_key()
        await asyncio.to_thread(storage.put, key, png)
        outcome = Outcome(status="ready", image_key=key)
        PROVIDER_LATENCY.labels(provider=provider.name).observe(time.monotonic() - started)
    except Exception as exc:
        outcome = outcome_for_error(exc, attempts, now)
        log = logger.warning if outcome.status == "queued" else logger.error
        log(
            "Generation attempt failed",
            generation_id=gid, attempt=attempts, error=str(exc), error_type=type(exc).__name__,
            outcome=outcome.status,
            retry_after=outcome.retry_after.isoformat() if outcome.retry_after else None,
        )
    with session_factory() as db:
        apply_outcome(db, gid, outcome, provider.name, provider.params(), now)
    if outcome.status in ("ready", "failed"):
        GENERATIONS_TOTAL.labels(provider=provider.name, status=outcome.status).inc()
    logger.info("Generation finished", generation_id=gid, status=outcome.status, provider=provider.name)
    return outcome.status


async def worker_loop(get_provider, get_storage, session_factory=SessionLocal, stop: asyncio.Event | None = None):
    """Poll-claim-run forever (until cancelled or `stop` is set). `get_provider` /
    `get_storage` are main.py's lazy accessors, passed in so this module never imports
    main. The queue-depth gauge is refreshed only when the queue is drained, so a busy
    replica never spends a session on bookkeeping between jobs."""
    logger.info("Generation worker started", poll_interval=POLL_INTERVAL, max_attempts=MAX_ATTEMPTS)
    while not (stop and stop.is_set()):
        try:
            row = await asyncio.to_thread(claim_next, session_factory)
            if row:
                await run_generation(row, provider=get_provider(), storage=get_storage(), session_factory=session_factory)
                continue  # drain the queue without sleeping between jobs
            with session_factory() as db:
                queued = db.execute(
                    select(func.count()).select_from(Generation).where(Generation.status == "queued")
                ).scalar()
            QUEUE_DEPTH.set(int(queued or 0))
        except Exception as e:
            logger.error("Worker error", error=str(e), exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
