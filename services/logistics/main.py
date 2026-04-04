import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, Body, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Column, Integer, String, DateTime, text
from sqlalchemy.orm import Session

from logger import get_logger, LoggingMiddleware
from database import Base, engine, get_db, SessionLocal
from metrics import metrics_endpoint, track_metrics
from auth import require_courier_or_admin, optional_auth
import orders_client

logger = get_logger(__name__)

ROOT_PATH = os.getenv("ROOT_PATH", "")
LOGISTICS_AUTO_ADVANCE_INTERVAL = int(os.getenv("LOGISTICS_AUTO_ADVANCE_INTERVAL", "120"))
WORKER_POLL_INTERVAL = 30  # seconds; separate from advance interval

background_task = None


# --- Models ---

class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"schema": "logistics_schema"}
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="preparing")
    tracking = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Helpers ---

def shipment_to_dict(s):
    return {
        "id": s.id,
        "order_id": s.order_id,
        "status": s.status,
        "tracking": s.tracking,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


# --- Background Worker ---

async def shipment_worker():
    """Auto-advance shipment statuses based on configurable timer."""
    logger.info("Shipment worker started",
                advance_interval=LOGISTICS_AUTO_ADVANCE_INTERVAL,
                poll_interval=WORKER_POLL_INTERVAL)
    while True:
        try:
            with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                shipments = db.query(Shipment).filter(
                    Shipment.status.in_(["dispatched", "in_transit"])
                ).all()
                for s in shipments:
                    # updated_at is naive (no tzinfo from DB) — must attach UTC before subtracting
                    age = (now - s.updated_at.replace(tzinfo=timezone.utc)).total_seconds()
                    if age >= LOGISTICS_AUTO_ADVANCE_INTERVAL:
                        old_status = s.status
                        s.status = "in_transit" if s.status == "dispatched" else "delivered"
                        s.updated_at = datetime.utcnow()
                        db.commit()
                        logger.info("Auto-advanced shipment",
                                    shipment_id=s.id,
                                    from_status=old_status,
                                    to_status=s.status,
                                    order_id=s.order_id)
                        if s.status == "delivered":
                            asyncio.create_task(
                                orders_client.notify_order_delivered(s.order_id)
                            )
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


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "logistics"}


@app.get("/readyz")
def readyz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# --- Endpoints ---

@app.post("/ship")
def create_shipment(order_id: int = Body(...), db: Session = Depends(get_db)):
    """
    Create a new shipment for an order.
    Called internally by the production service when an order is ready to ship.
    """
    # Check if shipment already exists for this order
    existing = db.query(Shipment).filter(Shipment.order_id == order_id).first()
    if existing:
        return {"shipment_id": existing.id, "tracking": existing.tracking}

    s = Shipment(order_id=order_id, status="dispatched", tracking=f"TRK-{order_id:06d}")
    db.add(s)
    db.commit()
    db.refresh(s)
    logger.info(f"Created shipment {s.id} for order {order_id}")
    return {"shipment_id": s.id, "tracking": s.tracking}


@app.get("/shipments")
def list_shipments(db: Session = Depends(get_db)):
    """List all shipments (for admin dashboard)."""
    shipments = db.query(Shipment).order_by(Shipment.id.desc()).all()
    return [shipment_to_dict(s) for s in shipments]


@app.get("/shipments/order/{order_id}")
def get_shipment_by_order(order_id: int, db: Session = Depends(get_db)):
    """Get shipment by order ID (for order tracking)."""
    s = db.query(Shipment).filter(Shipment.order_id == order_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment_to_dict(s)


@app.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    """Get shipment by ID."""
    s = db.get(Shipment, shipment_id)
    if not s:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment_to_dict(s)


@app.put("/shipments/{shipment_id}/status")
async def update_shipment_status(
    shipment_id: int,
    background_tasks: BackgroundTasks,
    status: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    claims: dict = Depends(optional_auth),  # Optional for now, can enable with require_courier_or_admin
):
    """
    Update shipment status.
    When status changes to 'delivered', automatically notifies the orders service.

    In production, this endpoint would require courier authentication.
    For external delivery integrations, this could be called via webhook.
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
    db.commit()
    db.refresh(s)

    logger.info(f"Shipment {shipment_id} status updated: {old_status} -> {status}")

    # If delivered, notify orders service
    if status == "delivered" and old_status != "delivered":
        background_tasks.add_task(orders_client.notify_order_delivered, s.order_id)
        logger.info(f"Queued order delivery notification for order {s.order_id}")

    # Log who made the update if authenticated
    if claims:
        logger.info(f"Status update by user: {claims.get('sub')} (role: {claims.get('role')})")

    return shipment_to_dict(s)


# --- External Integration Endpoints ---

@app.post("/webhooks/delivery-update")
async def external_delivery_webhook(
    background_tasks: BackgroundTasks,
    tracking_number: str = Body(...),
    status: str = Body(...),
    db: Session = Depends(get_db),
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
