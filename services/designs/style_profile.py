"""Style profile (D-07 tier 2 / D-16): a short summary of the customer's taste built from
their prompts and purchases.

Refreshed lazily — never inside the ORDER_PAID handler (10 s outbox budget) — by the
worker when 'Personalise' is on and the profile is stale, or on demand from the studio
page. Named style_profile (not profile) because `profile` is a stdlib module and the
uvicorn/pytest path order must never decide which one wins.

Inputs: the customer's last PROMPT_WINDOW non-failed prompts and the names of their last
PURCHASE_WINDOW purchases (ORDER_PAID, events.py), deduplicated. The summariser
(summarizer.py: OpenAI chat or the deterministic keyword fallback) turns them into 1-2
sentences stored on style_profiles.summary; a personalised generation sends
    prompt + STYLE_NOTES_PREFIX + summary
to the provider and stores it as effective_prompt so the thesis can show the diff.

Failure contract: a summariser outage keeps the previous summary (the profile stays
stale and is retried on the next personalised generation); ensure_summary never raises,
because a profile problem must never fail a generation.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from database import SessionLocal
from logger import get_logger
from models import Generation, Purchase, StyleProfile
from summarizer import get_summarizer

logger = get_logger(__name__)

PROMPT_WINDOW = 20
PURCHASE_WINDOW = 20
STYLE_NOTES_PREFIX = "\n\nStyle notes: "

_summarizer = None


def default_summarizer():
    """The configured Summarizer, built on first use (one client per process)."""
    global _summarizer
    if _summarizer is None:
        _summarizer = get_summarizer()
    return _summarizer


def gather_inputs(db, email: str) -> tuple[list[str], list[str]]:
    """The customer's newest PROMPT_WINDOW prompts (failed generations excluded) and the
    names of their newest PURCHASE_WINDOW purchases, deduplicated, newest first."""
    prompts = db.execute(
        select(Generation.prompt)
        .where(Generation.customer_email == email, Generation.status != "failed")
        .order_by(Generation.created_at.desc(), Generation.id.desc())
        .limit(PROMPT_WINDOW)
    ).scalars().all()
    names = db.execute(
        select(Purchase.name)
        .where(Purchase.customer_email == email)
        .order_by(Purchase.purchased_at.desc(), Purchase.id.desc())
        .limit(PURCHASE_WINDOW)
    ).scalars().all()
    return list(prompts)[:PROMPT_WINDOW], list(dict.fromkeys(n for n in names if n))


def compose_effective_prompt(prompt: str, summary: str | None) -> str:
    """prompt + "Style notes" when there is a summary; the prompt unchanged otherwise."""
    if summary and summary.strip():
        return f"{prompt}{STYLE_NOTES_PREFIX}{summary.strip()}"
    return prompt


def mark_stale(db, email: str) -> None:
    """Flag the customer's profile for a lazy refresh; a customer without a profile gets
    a stale placeholder row so the next personalised generation builds one."""
    prof = db.get(StyleProfile, email)
    if prof is None:
        db.add(StyleProfile(customer_email=email, stale=True))
    else:
        prof.stale = True


async def refresh_profile(db, email: str, summarizer=None, now: datetime | None = None) -> StyleProfile:
    """Rebuild the summary from the customer's rows and commit. On a summariser failure
    (ProviderError for 429/5xx/network, or anything unexpected) the previous summary is
    kept, nothing is committed and the profile stays stale for the next attempt."""
    now = now or datetime.now(timezone.utc)
    summarizer = summarizer or default_summarizer()

    # Every SQL statement runs in the threadpool, never on the event loop.
    def _load() -> tuple:
        prof = db.get(StyleProfile, email)
        if prof is None:
            prof = StyleProfile(customer_email=email, stale=True)
            db.add(prof)
        prompts, purchases = gather_inputs(db, email)
        return prof, prompts, purchases

    prof, prompts, purchases = await run_in_threadpool(_load)
    if not prompts and not purchases:
        summary = ""
    else:
        try:
            summary = await summarizer.summarize(prompts, purchases)
        except Exception as e:
            logger.warning(
                "Style summary refresh failed; keeping the previous summary",
                customer=email, summarizer=getattr(summarizer, "name", "?"), error=str(e),
            )
            return prof
    def _store() -> None:
        prof.summary = summary
        prof.prompt_count = len(prompts)
        prof.purchase_count = len(purchases)
        prof.stale = False
        prof.updated_at = now
        db.commit()
        db.refresh(prof)  # the callers read prof.* after the commit

    await run_in_threadpool(_store)
    logger.info(
        "Style profile refreshed",
        customer=email, summarizer=getattr(summarizer, "name", "?"),
        prompt_count=len(prompts), purchase_count=len(purchases), summary_chars=len(summary or ""),
    )
    return prof


async def ensure_summary(email: str, summarizer=None, session_factory=SessionLocal) -> str | None:
    """The cached summary when the profile is fresh; a refresh when it is missing or stale.
    NEVER raises: on any failure the summary read before the failure (or None) is returned."""
    old = None
    try:
        db = session_factory()  # no I/O until the first statement
        try:
            prof = await run_in_threadpool(db.get, StyleProfile, email)
            if prof is not None:
                old = prof.summary or None
                if not prof.stale:
                    return old
            prof = await refresh_profile(db, email, summarizer)
            return prof.summary or None
        finally:
            await run_in_threadpool(db.close)  # may ROLLBACK an open read: off the loop
    except Exception as e:
        logger.warning("ensure_summary failed; generating without style notes", customer=email, error=str(e))
        return old
