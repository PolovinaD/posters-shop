"""Background generation worker (D-02 / D-04 / D-05).

One loop per replica, started from main.py's lifespan. Each iteration:

  sweep  -> every SWEEP_INTERVAL s, RECLAIM_SQL hands `generating` rows older than
            STALE_AFTER back to `queued` (or `failed` once out of attempts): a
            worker that died mid-call left them behind
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

Crash recovery: the claim consumed the attempt before the worker died, and the sweep
does not hand it back, so a poison row that crashes the pod fails after MAX_ATTEMPTS.

Personalise (D-07/D-16): before the provider call, a row with `personalise` asks
style_profile.ensure_summary for the customer's style summary (cached when fresh,
refreshed when stale or missing, never raising) and sends
prompt + "Style notes: " + summary; what was actually sent is written back as
`effective_prompt`.

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
from style_profile import ensure_summary, compose_effective_prompt

logger = get_logger(__name__)

POLL_INTERVAL = float(os.getenv("DESIGNS_WORKER_POLL_INTERVAL", "1.0"))
MAX_ATTEMPTS = int(os.getenv("DESIGNS_MAX_ATTEMPTS", "3"))
# Seconds a `generating` row may sit before its claim is presumed dead (the worker died
# mid-call): must exceed the longest provider call (OpenAI 180 s httpx timeout, Replicate
# 90 s per call + 180 s poll deadline) plus the storage put, so 600 s is safe.
STALE_AFTER = float(os.getenv("DESIGNS_STALE_AFTER", "600"))
# Seconds between stale-claim sweeps.
SWEEP_INTERVAL = float(os.getenv("DESIGNS_SWEEP_INTERVAL", "60"))
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

# Crash recovery: a worker that dies mid-call (provider call or storage put) leaves its
# row `generating`, and nothing else ever selects that status. The sweep hands such rows
# back once their claim is older than STALE_AFTER. The crashed attempt stays consumed
# (the claim already incremented it), so a poison row that crashes the pod fails after
# DESIGNS_MAX_ATTEMPTS instead of cycling forever.
RECLAIM_SQL = text("""
    UPDATE designs_schema.generations
       SET status = CASE WHEN attempts >= :max_attempts THEN 'failed' ELSE 'queued' END,
           failure_reason = CASE WHEN attempts >= :max_attempts THEN :reason ELSE failure_reason END,
           finished_at = CASE WHEN attempts >= :max_attempts THEN now() ELSE finished_at END,
           retry_after = NULL
     WHERE status = 'generating' AND started_at < now() - make_interval(secs => :stale)
 RETURNING id, attempts, status
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


def reclaim_stale(session_factory=SessionLocal) -> list[dict]:
    """Hand back `generating` rows whose claim is older than STALE_AFTER (their worker
    died mid-call): back to queued, or failed when they are out of attempts. Returns
    the reclaimed rows as plain dicts. The session is closed on return."""
    with session_factory() as db:
        rows = db.execute(
            RECLAIM_SQL, {"stale": STALE_AFTER, "max_attempts": MAX_ATTEMPTS, "reason": UNAVAILABLE_REASON}
        ).mappings().all()
        db.commit()
    reclaimed = [dict(r) for r in rows]
    for r in reclaimed:
        logger.warning(
            "Reclaimed stale generation",
            generation_id=r["id"], attempts=r["attempts"], status=r["status"], stale_after=STALE_AFTER,
        )
    return reclaimed


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


def apply_outcome(
    db, generation_id: int, outcome: Outcome, provider_name: str, params: dict, now: datetime,
    effective_prompt: str | None = None,
) -> None:
    """Write one attempt's outcome onto the row and commit. A vanished row is a no-op.
    `effective_prompt` is what was actually sent to the provider (the prompt plus the
    style notes when personalised); None leaves the column untouched."""
    gen = db.get(Generation, generation_id)
    if gen is None:
        return
    gen.status = outcome.status
    gen.provider = provider_name
    gen.params = params
    if effective_prompt is not None:
        gen.effective_prompt = effective_prompt
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
    gid, email, attempts = row["id"], row["customer_email"], int(row.get("attempts") or 1)
    prompt = row.get("effective_prompt") or row["prompt"]
    if row.get("personalise"):
        # Outside the breaker: the summariser has its own failure handling and never raises here.
        summary = await ensure_summary(email, session_factory=session_factory)
        prompt = compose_effective_prompt(row["prompt"], summary)
    started = time.monotonic()
    error = None
    try:
        png = await breaker.call(lambda: provider.generate(prompt, user_ref(email)))
        key = new_image_key()
        await asyncio.to_thread(storage.put, key, png)
        outcome = Outcome(status="ready", image_key=key)
        PROVIDER_LATENCY.labels(provider=provider.name).observe(time.monotonic() - started)
    except Exception as exc:
        error = exc
    # Read the clock AFTER the provider call: finished_at and retry_after must mark when the
    # attempt ended, not when it began (a real provider takes 10-60 s; the fake one 60 ms).
    now = now or datetime.now(timezone.utc)
    if error is not None:
        outcome = outcome_for_error(error, attempts, now)
        log = logger.warning if outcome.status == "queued" else logger.error
        log(
            "Generation attempt failed",
            generation_id=gid, attempt=attempts, error=str(error), error_type=type(error).__name__,
            outcome=outcome.status,
            retry_after=outcome.retry_after.isoformat() if outcome.retry_after else None,
        )
    def _persist() -> None:
        with session_factory() as db:
            apply_outcome(db, gid, outcome, provider.name, provider.params(), now, effective_prompt=prompt)

    await asyncio.to_thread(_persist)
    if outcome.status in ("ready", "failed"):
        GENERATIONS_TOTAL.labels(provider=provider.name, status=outcome.status).inc()
    logger.info("Generation finished", generation_id=gid, status=outcome.status, provider=provider.name)
    return outcome.status


async def worker_loop(get_provider, get_storage, session_factory=SessionLocal, stop: asyncio.Event | None = None):
    """Poll-claim-run forever (until cancelled or `stop` is set). `get_provider` /
    `get_storage` are main.py's lazy accessors, passed in so this module never imports
    main. The queue-depth gauge is refreshed only when the queue is drained, so a busy
    replica never spends a session on bookkeeping between jobs. The stale-claim sweep
    runs before the first claim and then at most once per SWEEP_INTERVAL, ahead of the
    claim, so it fires on a busy replica too."""
    logger.info(
        "Generation worker started",
        poll_interval=POLL_INTERVAL, max_attempts=MAX_ATTEMPTS,
        stale_after=STALE_AFTER, sweep_interval=SWEEP_INTERVAL,
    )
    last_sweep: float | None = None
    while not (stop and stop.is_set()):
        try:
            # Sweep BEFORE the claim: a replica whose queue never drains must still sweep, so the
            # queue-drained branch below is the wrong place for it.
            if last_sweep is None or time.monotonic() - last_sweep >= SWEEP_INTERVAL:
                await asyncio.to_thread(reclaim_stale, session_factory)
                last_sweep = time.monotonic()
            row = await asyncio.to_thread(claim_next, session_factory)
            if row:
                await run_generation(row, provider=get_provider(), storage=get_storage(), session_factory=session_factory)
                continue  # drain the queue without sleeping between jobs
            def _queue_depth():
                with session_factory() as db:
                    return db.execute(
                        select(func.count()).select_from(Generation).where(Generation.status == "queued")
                    ).scalar()

            queued = await asyncio.to_thread(_queue_depth)
            QUEUE_DEPTH.set(int(queued or 0))
        except Exception as e:
            logger.error("Worker error", error=str(e), exc_info=True)
        await asyncio.sleep(POLL_INTERVAL)
