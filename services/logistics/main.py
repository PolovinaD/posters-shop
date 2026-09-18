import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from logger import get_logger, LoggingMiddleware
from bulkhead import BulkheadMiddleware, bulkhead_limit, bulkhead_queue_timeout
from service_auth import require_service_or_owner
from database import engine, get_db, SessionLocal
from models import Shipment
from worker_rules import next_status, courier_binding_wallet, courier_id_from_claims
from metrics import metrics_endpoint, track_metrics
from auth import require_courier_or_admin, optional_auth
import orders_client

logger = get_logger(__name__)

ROOT_PATH = os.getenv("ROOT_PATH", "")
READYZ_TIMEOUT_SECONDS = 2.0
LOGISTICS_AUTO_ADVANCE_INTERVAL = int(os.getenv("LOGISTICS_AUTO_ADVANCE_INTERVAL", "120"))
LOGISTICS_DEFAULT_COURIER_WALLET = os.getenv("LOGISTICS_DEFAULT_COURIER_WALLET") or None  # wallet the unattended worker binds on pick-up (compose: Ganache account[2])
WORKER_POLL_INTERVAL = 30  # seconds; separate from advance interval

background_task = None


# --- Helpers ---

def shipment_to_dict(s):
    return {
        "id": s.id,
        "order_id": s.order_id,
        "status": s.status,
        "tracking": s.tracking,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "courier_id": s.courier_id,
        "courier_wallet": s.courier_wallet,
        "courier_bound_at": s.courier_bound_at.isoformat() if s.courier_bound_at else None,
        "shipping_address": {
            "recipient_name": s.recipient_name,
            "street": s.street,
            "city": s.city,
            "postal_code": s.postal_code,
            "country": s.country,
            "phone": s.recipient_phone,
        } if s.recipient_name else None,
    }


# --- Background Worker ---

async def shipment_worker():
    """Auto-advance shipment statuses based on configurable timer."""
    logger.info("Shipment worker started",
                advance_interval=LOGISTICS_AUTO_ADVANCE_INTERVAL,
                poll_interval=WORKER_POLL_INTERVAL)
    while True:
        try:
            # expire_on_commit=False: the pass keeps reading rows it just committed
            # (log lines and the next shipment) and reads no server-generated column.
            # Every SQL statement runs via run_in_threadpool, never on the event loop.
            db = SessionLocal(expire_on_commit=False)
            try:
                now = datetime.now(timezone.utc)

                def _fetch() -> list:
                    return db.query(Shipment).filter(
                        Shipment.status.in_(["dispatched", "in_transit"])
                    ).all()

                shipments = await run_in_threadpool(_fetch)
                for s in shipments:
                    new_status = next_status(
                        s.status, s.updated_at, now, LOGISTICS_AUTO_ADVANCE_INTERVAL
                    )
                    if new_status is not None:
                        old_status = s.status
                        s.status = new_status
                        s.updated_at = datetime.utcnow()
                        # Unattended pick-up: record "system" (NULL courier_id) + the
                        # default wallet in the same transaction as the status change
                        wallet = courier_binding_wallet(old_status, s.status, None, LOGISTICS_DEFAULT_COURIER_WALLET)
                        if wallet:
                            s.courier_id = None
                            s.courier_wallet = wallet
                            s.courier_bound_at = datetime.utcnow()
                        await run_in_threadpool(db.commit)
                        logger.info("Auto-advanced shipment",
                                    shipment_id=s.id,
                                    from_status=old_status,
                                    to_status=s.status,
                                    order_id=s.order_id)
                        if wallet:
                            asyncio.create_task(
                                orders_client.notify_courier_assigned(s.order_id, wallet)
                            )
                        if s.status == "delivered":
                            asyncio.create_task(
                                orders_client.notify_order_delivered(s.order_id)
                            )
            finally:
                await run_in_threadpool(db.close)
        except Exception as e:
            logger.error("Shipment worker error", error=str(e))
        await asyncio.sleep(WORKER_POLL_INTERVAL)


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for logistics service."""
    global background_task
    logger.info("Logistics service starting, migrations managed by Alembic")
    background_task = asyncio.create_task(shipment_worker())
    yield
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    logger.info("Logistics service shutdown complete")


app = FastAPI(title="logistics service", lifespan=lifespan, root_path=ROOT_PATH)

# First add_middleware = innermost: a request reaches the bulkhead only after CORS, the
# metrics middleware and the request log have seen it, so a shed request is still logged
# with its correlation id and counted in http_requests_total. Limit = pool_size +
# max_overflow (BULKHEAD_LIMIT overrides), queue bounded by BULKHEAD_QUEUE_TIMEOUT (10 s).
app.add_middleware(
    BulkheadMiddleware,
    limit=bulkhead_limit(engine),
    queue_timeout=bulkhead_queue_timeout(),
)
app.add_middleware(LoggingMiddleware)
app.middleware("http")(track_metrics)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def _db_ping() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@app.get("/healthz")
async def healthz():
    """Liveness. Pure: no database, no threadpool — a busy pod is still alive."""
    return {"status": "ok", "service": "logistics"}


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


# --- Endpoints ---

@app.post("/ship")
async def create_shipment(order_id: int = Body(...), db: Session = Depends(get_db), claims: dict = Depends(require_service_or_owner)):
    """
    Create a new shipment for an order.
    Called internally by the production service when an order is ready to ship.

    The delivery address is fetched from orders exactly here, once, and then
    copied into this schema — every later courier read is served locally.
    """
    # Check if shipment already exists for this order (SQL off the event loop)
    def _existing():
        return db.query(Shipment).filter(Shipment.order_id == order_id).first()

    existing = await run_in_threadpool(_existing)
    if existing:
        return {"shipment_id": existing.id, "tracking": existing.tracking}

    address = await orders_client.fetch_shipping_address(order_id)
    if not address:
        logger.warning("Creating shipment without a delivery address", order_id=order_id)
        address = {}

    def _create() -> Shipment:
        s = Shipment(
            order_id=order_id,
            status="dispatched",
            tracking=f"TRK-{order_id:06d}",
            recipient_name=address.get("recipient_name"),
            street=address.get("street"),
            city=address.get("city"),
            postal_code=address.get("postal_code"),
            country=address.get("country"),
            recipient_phone=address.get("phone"),
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    s = await run_in_threadpool(_create)
    logger.info(f"Created shipment {s.id} for order {order_id}")
    return {"shipment_id": s.id, "tracking": s.tracking}


# The three shipment reads below are guarded by require_courier_or_admin. They
# never carried any authorization (pre-existing, not introduced by 260912-n7c --
# `git show 23f6972:services/logistics/main.py` shows only Depends(get_db)). That
# was a latent missing-authorization defect until 260912-n7c added shipping_address
# to shipment_to_dict, which turned it into a live customer-PII disclosure: one
# unauthenticated GET through the public nginx proxy returned every customer's
# name, street, city, postal code and phone.
@app.get("/shipments")
def list_shipments(
    db: Session = Depends(get_db),
    claims: dict = Depends(require_courier_or_admin),
):
    """List all shipments (for admin dashboard). Requires courier or owner role."""
    shipments = db.query(Shipment).order_by(Shipment.id.desc()).all()
    return [shipment_to_dict(s) for s in shipments]


@app.get("/shipments/order/{order_id}")
def get_shipment_by_order(
    order_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_courier_or_admin),
):
    """Get shipment by order ID. Requires courier or owner role."""
    s = db.query(Shipment).filter(Shipment.order_id == order_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment_to_dict(s)


@app.get("/shipments/{shipment_id}")
def get_shipment(
    shipment_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_courier_or_admin),
):
    """Get shipment by ID. Requires courier or owner role."""
    s = db.get(Shipment, shipment_id)
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment_to_dict(s)


@app.put("/shipments/{shipment_id}/status")
def update_shipment_status(
    shipment_id: int,
    background_tasks: BackgroundTasks,
    status: str = Body(..., embed=True),
    courier_wallet: str | None = Body(default=None, pattern=r"^0x[0-9a-fA-F]{40}$"),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_courier_or_admin),
):
    """
    Update shipment status. Requires courier or owner role.
    On dispatched -> in_transit the courier's wallet (body `courier_wallet`, else
    LOGISTICS_DEFAULT_COURIER_WALLET) is sent to orders for escrow binding.
    The binding (courier_id = caller's sub, courier_wallet, courier_bound_at) is recorded on the shipment.
    When status changes to 'delivered', automatically notifies the orders service.
    """
    s = db.get(Shipment, shipment_id)
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")

    # Valid status transitions
    valid_statuses = ["dispatched", "in_transit", "delivered"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
        )

    # Validate state transitions
    current_idx = valid_statuses.index(s.status) if s.status in valid_statuses else -1
    new_idx = valid_statuses.index(status)

    if new_idx < current_idx:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {s.status} to {status}"
        )

    old_status = s.status
    s.status = status

    # Pick-up: record who bound which wallet, in the same transaction as the
    # status change. orders keeps its own courier_wallet snapshot (CONTRACT B).
    wallet = courier_binding_wallet(old_status, status, courier_wallet, LOGISTICS_DEFAULT_COURIER_WALLET)
    if wallet:
        s.courier_id = courier_id_from_claims(claims)
        s.courier_wallet = wallet
        s.courier_bound_at = datetime.utcnow()

    db.commit()
    db.refresh(s)

    logger.info(f"Shipment {shipment_id} status updated: {old_status} -> {status}")

    # Pick-up: hand the courier's wallet to orders (CONTRACT B), never blocking the courier
    if wallet:
        background_tasks.add_task(orders_client.notify_courier_assigned, s.order_id, wallet)
        logger.info(f"Queued courier binding for order {s.order_id} (wallet {wallet[:10]}…, courier {s.courier_id or 'system'})")

    # If delivered, notify orders service
    if status == "delivered" and old_status != "delivered":
        background_tasks.add_task(orders_client.notify_order_delivered, s.order_id)
        logger.info(f"Queued order delivery notification for order {s.order_id}")

    logger.info(f"Status update by user: {claims.get('sub')} (role: {claims.get('role')})")

    return shipment_to_dict(s)


# --- External Integration Endpoints ---

@app.post("/webhooks/delivery-update")
def external_delivery_webhook(
    background_tasks: BackgroundTasks,
    tracking_number: str = Body(...),
    status: str = Body(...),
    db: Session = Depends(get_db),
    claims: dict = Depends(require_service_or_owner),
):
    """
    Webhook endpoint for external delivery companies (DHL, FedEx, etc.)
    to push status updates.

    In production, this would verify webhook signatures from the delivery provider.
    """
    # Find shipment by tracking number
    s = db.query(Shipment).filter(Shipment.tracking == tracking_number).first()
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")

    # Map external status to internal status
    status_mapping = {
        "picked_up": "dispatched",
        "in_transit": "in_transit",
        "out_for_delivery": "in_transit",
        "delivered": "delivered",
    }

    internal_status = status_mapping.get(status.lower())
    if not internal_status:
        logger.warning(f"Unknown external status: {status}")
        return {"received": True, "mapped": False}

    old_status = s.status
    s.status = internal_status
    s.updated_at = datetime.utcnow()
    db.commit()

    logger.info(f"External webhook updated shipment {s.id}: {old_status} -> {internal_status}")

    # If delivered, notify orders service
    if internal_status == "delivered" and old_status != "delivered":
        background_tasks.add_task(orders_client.notify_order_delivered, s.order_id)

    return {"received": True, "mapped": True, "internal_status": internal_status}
