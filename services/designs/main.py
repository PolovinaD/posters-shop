"""
Designs Service — AI poster studio.

Customer-facing API (all JWT-scoped to the caller's e-mail) and the background
generation worker:

  POST /generations              202 + the queued row; the shop polls GET /generations/{id}
  GET  /generations[/{id}]       the caller's own rows, newest first / one row or 404
  GET  /me/quota                 D-14 daily allowance (limit / used / remaining / resets_at)
  GET  /me/style-profile         D-07 tier 2: the caller's style summary, counts and `stale`
  POST /me/style-profile/refresh rebuild it now through the summariser (D-16)
  GET|POST|DELETE /saved-prompts the caller's saved prompts
  POST /generations/{id}/print   Print-this (D-06): an unlisted catalog family AI-{id} with
                                 A4..A1 variants + virtual stock; 201 created / 200 already printed
  GET  /images/{key}             the PNG bytes, immutable cache headers, NO bearer required
                                 (an <img> cannot send one; the 32-hex key is the capability)
  POST /events/order-paid        the orders outbox's third ORDER_PAID subscriber (D-07):
                                 service or owner token; DB-only and idempotent (events.py)
  GET  /admin/generations        every customer's rows, newest first; owner only (?customer=, ?status=)

The worker (worker.py) is started in lifespan with asyncio.create_task and cancelled
on shutdown (production's job_worker shape).

The image provider (providers.py, IMAGE_PROVIDER env) and the storage backend
(storage.py, STORAGE_BACKEND env) are built lazily through provider()/storage(),
so importing this module never touches the filesystem or the network — unit tests
import it without running the lifespan.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

import catalog_client
import inventory_client
from auth import get_current_user_claims, require_owner
from circuit_breaker import CircuitOpenError
from database import engine, get_db
from events import process_order_paid
from logger import get_logger, LoggingMiddleware
from metrics import metrics_endpoint, track_metrics, SERVICE_NAME
from models import Generation, SavedPrompt, StyleProfile
from printing import print_generation
from providers import get_image_provider
from quota import check_quota, quota_status
from schemas import (
    AdminGenerationOut, GenerationCreate, GenerationOut, OutboxEventPayload, PrintOut, QuotaOut,
    SavedPromptCreate, SavedPromptOut, StyleProfileOut,
)
from service_auth import require_service_or_owner
from storage import get_storage
from style_profile import refresh_profile
from summarizer import get_summarizer
from worker import worker_loop

ROOT_PATH = os.getenv("ROOT_PATH", "")
READYZ_TIMEOUT_SECONDS = 2.0
AI_DAILY_QUOTA = int(os.getenv("AI_DAILY_QUOTA", "10"))  # D-14; 0 = unlimited
# Where the shop reaches GET /images/{key}: through the nginx/vite proxy in compose and
# on EKS (LocalStorage); a CDN/bucket URL when S3 serves the files directly.
PUBLIC_URL_PREFIX = os.getenv("DESIGNS_PUBLIC_URL_PREFIX", "/api/designs/images").rstrip("/")
PRODUCT_URL_PREFIX = "/shop/product"
# Print-this (D-11/D-12): the A3 price; A4/A2/A1 follow the catalog seed ladder (-5/+10/+25).
AI_POSTER_BASE_PRICE = Decimal(os.getenv("AI_POSTER_BASE_PRICE", "29.99"))
# "Virtual stock" per variant: print-on-demand never runs out, but orders reserves unconditionally.
AI_POSTER_STOCK = int(os.getenv("AI_POSTER_STOCK", "1000"))

logger = get_logger(__name__)

_provider = None
_storage = None
worker_task = None


def provider():
    """The configured ImageProvider, built on first use."""
    global _provider
    if _provider is None:
        _provider = get_image_provider()
    return _provider


def storage():
    """The configured Storage backend, built on first use."""
    global _storage
    if _storage is None:
        _storage = get_storage()
    return _storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info(
        "Designs service starting",
        image_provider=provider().name,
        provider_params=provider().params(),
        summarizer=get_summarizer().name,
        storage_backend=os.getenv("STORAGE_BACKEND", "local"),
        daily_quota=AI_DAILY_QUOTA,
    )
    global worker_task
    worker_task = asyncio.create_task(worker_loop(provider, storage))

    yield

    if worker_task:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


app = FastAPI(title=f"{SERVICE_NAME} service", lifespan=lifespan, root_path=ROOT_PATH)
app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ============== Health & Metrics ==============

def _db_ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@app.get("/healthz")
async def healthz():
    """Liveness. Pure: no database, no threadpool — a busy pod is still alive."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
async def readyz():
    """Readiness: database reachable within READYZ_TIMEOUT_SECONDS. The ping runs on
    the loop's default executor, not the request threadpool, so a saturated request
    pool does not make the pod NotReady; a slow or unreachable database does."""
    try:
        await asyncio.wait_for(asyncio.to_thread(_db_ping), timeout=READYZ_TIMEOUT_SECONDS)
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# ============== Generations ==============

def to_out(gen: Generation, model: type[GenerationOut] = GenerationOut) -> GenerationOut:
    """Row -> API shape. image_url is derived from image_key only once the image exists;
    product_url once "Print this" has attached a catalog product. `model` lets the admin
    route reuse the derivation for its wider AdminGenerationOut."""
    out = model.model_validate(gen)
    if gen.status == "ready" and gen.image_key:
        out.image_url = f"{PUBLIC_URL_PREFIX}/{gen.image_key}"
    if gen.catalog_product_sku:
        out.product_url = f"{PRODUCT_URL_PREFIX}/{gen.catalog_product_sku}"
    return out


def _own_generation(db: Session, generation_id: int, email: str) -> Generation:
    """The caller's own row or 404 — someone else's id is indistinguishable from a missing one."""
    gen = db.execute(
        select(Generation).where(Generation.id == generation_id, Generation.customer_email == email)
    ).scalar_one_or_none()
    if gen is None:
        raise HTTPException(status_code=404, detail="Generation not found")
    return gen


@app.post("/generations", response_model=GenerationOut, status_code=202)
def create_generation(
    payload: GenerationCreate,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """Queue a generation (D-02): the row is inserted as `queued` and the worker picks it
    up; the shop polls GET /generations/{id}. Over quota -> 429 + Retry-After (D-14)."""
    email, role = claims["sub"], claims.get("role")
    check_quota(db, email, role, AI_DAILY_QUOTA)
    prompt = payload.prompt.strip()
    gen = Generation(
        customer_email=email,
        prompt=prompt,
        effective_prompt=prompt,
        personalise=payload.personalise,
        provider=provider().name,
        params=provider().params(),
        status="queued",
        attempts=0,
    )
    db.add(gen)
    db.commit()
    db.refresh(gen)
    logger.info("Generation queued", generation_id=gen.id, personalise=gen.personalise)
    return to_out(gen)


@app.get("/generations", response_model=list[GenerationOut])
def list_generations(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """The caller's own generations, newest first."""
    rows = db.execute(
        select(Generation)
        .where(Generation.customer_email == claims["sub"])
        .order_by(desc(Generation.created_at), desc(Generation.id))
        .limit(limit)
    ).scalars().all()
    return [to_out(g) for g in rows]


@app.get("/generations/{generation_id}", response_model=GenerationOut)
def get_generation(
    generation_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    return to_out(_own_generation(db, generation_id, claims["sub"]))


@app.post("/generations/{generation_id}/print", response_model=PrintOut, status_code=201)
async def print_design(
    generation_id: int,
    response: Response,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """Print-this (D-06): turn the caller's ready design into an unlisted catalog family
    (AI-{id}, variants AI-{id}-A4..A1 on the seed ladder) plus virtual stock, through
    service-token calls to catalog and inventory. Idempotent: a design already printed
    answers 200 with the same payload. A downstream refusal is 502, an outage or open
    breaker 503 — and in both cases catalog_product_sku stays NULL so a retry completes
    whatever half is missing."""
    gen = await run_in_threadpool(_own_generation, db, generation_id, claims["sub"])
    if gen.status != "ready" or not gen.image_key:
        raise HTTPException(status_code=409, detail="Generation is not ready")
    image_url = f"{PUBLIC_URL_PREFIX}/{gen.image_key}"
    try:
        sku, created = await print_generation(
            db, gen, catalog=catalog_client, inventory=inventory_client, image_url=image_url,
            base_price=AI_POSTER_BASE_PRICE, stock=AI_POSTER_STOCK,
        )
    except (catalog_client.CatalogRejectedError, inventory_client.InventoryRejectedError) as e:
        logger.error("Print rejected downstream", generation_id=generation_id, error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not create the product: {e}")
    except (catalog_client.CatalogServiceError, inventory_client.InventoryServiceError, CircuitOpenError) as e:
        logger.error("Print failed downstream", generation_id=generation_id, error=str(e))
        raise HTTPException(status_code=503, detail="Catalog or inventory is unavailable; please try again")
    if not created:
        response.status_code = 200
    logger.info("Design printed", generation_id=generation_id, sku=sku, created=created)
    return PrintOut(sku=sku, product_url=f"{PRODUCT_URL_PREFIX}/{sku}", created=created)


# ============== Admin ==============

@app.get("/admin/generations", response_model=list[AdminGenerationOut])
def admin_list_generations(
    limit: int = Query(100, ge=1, le=200),
    customer: Optional[str] = Query(None, description="Exact customer e-mail"),
    status: Optional[str] = Query(None, pattern=r"^(queued|generating|ready|failed)$"),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_owner),
):
    """Every customer's generations, newest first — the admin dashboard's Designs page.
    Owner only; `customer` is an exact e-mail match, `status` one of the four states."""
    query = select(Generation)
    if customer:
        query = query.where(Generation.customer_email == customer.strip())
    if status:
        query = query.where(Generation.status == status)
    rows = db.execute(
        query.order_by(desc(Generation.created_at), desc(Generation.id)).limit(limit)
    ).scalars().all()
    return [to_out(g, AdminGenerationOut) for g in rows]


# ============== Quota ==============

@app.get("/me/quota", response_model=QuotaOut)
def me_quota(db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    return quota_status(db, claims["sub"], claims.get("role"), AI_DAILY_QUOTA)


# ============== Style profile ==============

@app.get("/me/style-profile", response_model=StyleProfileOut)
def get_style_profile(db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """The caller's style summary as stored — `stale` tells the shop a refresh is pending
    (after a purchase, or before any summary exists)."""
    prof = db.get(StyleProfile, claims["sub"])
    return StyleProfileOut.model_validate(prof) if prof else StyleProfileOut()


@app.post("/me/style-profile/refresh", response_model=StyleProfileOut)
async def refresh_style_profile(db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """Rebuild the summary now from the caller's prompts and purchases (D-16). A summariser
    outage keeps the previous summary and answers 200 with `stale: true`."""
    return StyleProfileOut.model_validate(await refresh_profile(db, claims["sub"]))


# ============== Saved prompts ==============

@app.get("/saved-prompts", response_model=list[SavedPromptOut])
def list_saved_prompts(db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    return db.execute(
        select(SavedPrompt)
        .where(SavedPrompt.customer_email == claims["sub"])
        .order_by(desc(SavedPrompt.created_at), desc(SavedPrompt.id))
    ).scalars().all()


@app.post("/saved-prompts", response_model=SavedPromptOut, status_code=201)
def create_saved_prompt(
    payload: SavedPromptCreate,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    saved = SavedPrompt(customer_email=claims["sub"], title=payload.title.strip(), prompt=payload.prompt.strip())
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@app.delete("/saved-prompts/{saved_prompt_id}", status_code=204)
def delete_saved_prompt(
    saved_prompt_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    email = claims["sub"]
    saved = db.execute(
        select(SavedPrompt).where(SavedPrompt.id == saved_prompt_id, SavedPrompt.customer_email == email)
    ).scalar_one_or_none()
    if saved is None or saved.customer_email != email:
        raise HTTPException(status_code=404, detail="Saved prompt not found")
    db.delete(saved)
    db.commit()
    return Response(status_code=204)


# ============== Event Listeners (Outbox Pattern) ==============

@app.post("/events/order-paid")
def handle_order_paid(
    event: OutboxEventPayload,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_service_or_owner),
):
    """ORDER_PAID from the orders outbox (D-07): stamp purchased_at on own designs, record
    every item as a purchase, mark the style profile stale, dedup by event id. Answers 200
    for unknown SKUs and re-deliveries — a non-2xx would make the outbox re-deliver the
    whole event to production and notifications as well."""
    logger.info("Received ORDER_PAID event", event_id=event.event_id, aggregate_id=event.aggregate_id)
    return process_order_paid(db, event)


# ============== Images ==============

@app.get("/images/{key}")
@app.head("/images/{key}")  # browsers, proxies and CDNs probe images with HEAD; uvicorn drops the body
def get_image(key: str = Path(pattern=r"^[0-9a-f]{32}\.png$")):  # == storage.KEY_RE
    """Serve a generated PNG. Deliberately unauthenticated: <img> tags cannot send a
    bearer, and the unguessable 32-hex key is the capability. Keys never change, so
    the response is immutable for a year; anything not matching KEY_RE is rejected by
    the path validator before storage is asked."""
    try:
        data = storage().get(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    return Response(
        content=data,
        media_type="image/png",
        # keys are unique per image and never rewritten, so a year of immutable caching is safe
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": f'"{key}"'},
    )
