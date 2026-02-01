import logging
from fastapi import FastAPI, Depends, Body, HTTPException, BackgroundTasks
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import Session
from datetime import datetime

from database import Base, engine, get_db
from metrics import metrics_endpoint
from auth import require_courier_or_admin, optional_auth
import orders_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="logistics service")


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "logistics"}


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# --- Models ---

class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = {"schema": "logistics"}
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
