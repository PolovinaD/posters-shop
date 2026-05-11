import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware

ROOT_PATH = os.getenv("ROOT_PATH", "")
from sqlalchemy import select, update, delete, and_, text
from sqlalchemy.orm import Session

from database import Base, engine, get_db, SessionLocal
from models import Stock, Reservation, SCHEMA_NAME
from schemas import (
    StockCreate, StockUpdate, StockOut,
    ReserveRequest, ReserveResponse,
    ReleaseRequest, ReleaseResponse,
    CommitRequest, CommitResponse,
    StockCheckResponse, BulkStockCheck, BulkStockResponse,
)
from metrics import (
    metrics_endpoint, track_metrics,
    STOCK_LEVEL, ACTIVE_RESERVATIONS, RESERVATIONS_EXPIRED
)
from logger import get_logger, LoggingMiddleware
from auth import require_owner

logger = get_logger(__name__)

SERVICE_NAME = "inventory"
ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://orders:8000")

# Background task control
background_task = None


async def notify_order_reservation_expired(order_id: int) -> None:
    """
    Best-effort fire-and-forget notification to orders that a reservation
    for order_id has expired. The orders endpoint is idempotent — duplicates,
    unknown order_ids, and already-finalised orders all return 200.

    We intentionally swallow all exceptions: the worker has already released
    stock; failing to notify orders is a non-fatal divergence that the
    endpoint's idempotency contract tolerates on the next worker tick (when
    the reservation row is already 'expired', so this won't re-fire — see
    caveat: notification only fires on the tick that flipped the reservation).
    """
    url = f"{ORDERS_SERVICE_URL}/internal/orders/{order_id}/reservation-expired"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json={})
            if response.status_code >= 400:
                logger.warning(
                    "Order reservation-expired notification returned error",
                    order_id=order_id,
                    status_code=response.status_code,
                    body=response.text[:200],
                )
    except Exception as e:
        logger.warning(
            "Failed to notify orders of expired reservation",
            order_id=order_id,
            error=str(e),
        )


async def expire_reservations_worker():
    """Background worker that releases expired reservations every 30 seconds."""
    while True:
        try:
            with SessionLocal() as db:
                now = datetime.now(timezone.utc)
                
                # Find and process expired reservations atomically
                expired = db.execute(
                    select(Reservation).where(
                        and_(
                            Reservation.status == "active",
                            Reservation.expires_at < now
                        )
                    ).with_for_update(skip_locked=True)
                ).scalars().all()
                
                expired_count = 0
                order_ids_to_notify: set[int] = set()
                for reservation in expired:
                    # Return quantity to available stock
                    db.execute(
                        update(Stock)
                        .where(Stock.sku == reservation.sku)
                        .values(
                            available=Stock.available + reservation.quantity,
                            reserved=Stock.reserved - reservation.quantity
                        )
                    )

                    # Mark reservation as expired
                    reservation.status = "expired"
                    reservation.released_at = now
                    order_ids_to_notify.add(reservation.order_id)
                    expired_count += 1

                if expired_count > 0:
                    db.commit()
                    RESERVATIONS_EXPIRED.inc(expired_count)
                    logger.info("Released expired reservations", count=expired_count)

                    # Update metrics
                    _update_metrics(db)

                    # Fire-and-forget notify orders service per unique order_id.
                    # Tasks run on the running event loop; they do not block the
                    # 30-second sleep below. notify_* swallows all exceptions.
                    for order_id in order_ids_to_notify:
                        asyncio.create_task(notify_order_reservation_expired(order_id))

        except Exception as e:
            logger.error("Error in expire_reservations_worker", error=str(e))
        
        await asyncio.sleep(30)  # Run every 30 seconds


def _update_metrics(db: Session):
    """Update Prometheus metrics for stock levels."""
    stocks = db.execute(select(Stock)).scalars().all()
    for stock in stocks:
        STOCK_LEVEL.labels(sku=stock.sku).set(stock.available)
    
    active_count = db.execute(
        select(Reservation).where(Reservation.status == "active")
    ).scalars().all()
    ACTIVE_RESERVATIONS.set(len(active_count))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup
    logger.info("Database migrations managed by Alembic - run 'alembic upgrade head' to apply")
    
    # Start background worker
    global background_task
    background_task = asyncio.create_task(expire_reservations_worker())
    logger.info("Reservation expiry worker started")
    
    yield
    
    # Shutdown
    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutdown complete")


app = FastAPI(title=f"{SERVICE_NAME} service", lifespan=lifespan, root_path=ROOT_PATH)
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


# ============== Health & Metrics ==============

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


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


# ============== Stock Management ==============

@app.get("/stock", response_model=list[StockOut])
def list_stock(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: dict = Depends(require_owner)
):
    """List all stock items."""
    stocks = db.execute(
        select(Stock).offset(skip).limit(limit)
    ).scalars().all()
    return stocks


@app.get("/stock/{sku}", response_model=StockOut)
def get_stock(sku: str, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Get stock for a specific SKU."""
    stock = db.execute(
        select(Stock).where(Stock.sku == sku)
    ).scalar_one_or_none()
    
    if not stock:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    return stock


@app.post("/stock", response_model=StockOut, status_code=201)
def create_stock(payload: StockCreate, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Create a new stock item."""
    existing = db.execute(
        select(Stock).where(Stock.sku == payload.sku)
    ).scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"SKU '{payload.sku}' already exists")
    
    stock = Stock(
        sku=payload.sku,
        name=payload.name,
        available=payload.available,
        reserved=0
    )
    db.add(stock)
    db.commit()
    db.refresh(stock)
    
    STOCK_LEVEL.labels(sku=stock.sku).set(stock.available)
    return stock


@app.patch("/stock/{sku}", response_model=StockOut)
def update_stock(sku: str, payload: StockUpdate, db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Update stock item (name or available quantity)."""
    stock = db.execute(
        select(Stock).where(Stock.sku == sku)
    ).scalar_one_or_none()
    
    if not stock:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    
    if payload.name is not None:
        stock.name = payload.name
    if payload.available is not None:
        stock.available = payload.available
    
    db.commit()
    db.refresh(stock)
    
    STOCK_LEVEL.labels(sku=stock.sku).set(stock.available)
    return stock


@app.post("/stock/{sku}/restock", response_model=StockOut)
def restock(sku: str, quantity: int = Query(..., gt=0), db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Add quantity to existing stock."""
    stock = db.execute(
        select(Stock).where(Stock.sku == sku)
    ).scalar_one_or_none()
    
    if not stock:
        raise HTTPException(status_code=404, detail=f"SKU '{sku}' not found")
    
    stock.available += quantity
    db.commit()
    db.refresh(stock)
    
    STOCK_LEVEL.labels(sku=stock.sku).set(stock.available)
    return stock


@app.post("/stock/check", response_model=BulkStockResponse)
def check_stock_bulk(payload: BulkStockCheck, db: Session = Depends(get_db)):
    """Check availability for multiple SKUs."""
    stocks = db.execute(
        select(Stock).where(Stock.sku.in_(payload.skus))
    ).scalars().all()
    
    stock_map = {s.sku: s for s in stocks}
    items = []
    
    for sku in payload.skus:
        if sku in stock_map:
            s = stock_map[sku]
            items.append(StockCheckResponse(
                sku=s.sku,
                available=s.available,
                reserved=s.reserved,
                can_reserve=s.available
            ))
        else:
            items.append(StockCheckResponse(
                sku=sku,
                available=0,
                reserved=0,
                can_reserve=0
            ))
    
    return BulkStockResponse(items=items)


# ============== Reservation Management ==============

@app.post("/reserve", response_model=ReserveResponse)
def reserve_stock(payload: ReserveRequest, db: Session = Depends(get_db)):
    """
    Reserve stock for an order. Uses atomic update to prevent overselling.
    
    The reservation will automatically expire after ttl_minutes (default 15).
    """
    # Atomic stock decrement - only succeeds if enough available
    result = db.execute(
        update(Stock)
        .where(
            and_(
                Stock.sku == payload.sku,
                Stock.available >= payload.quantity
            )
        )
        .values(
            available=Stock.available - payload.quantity,
            reserved=Stock.reserved + payload.quantity
        )
        .returning(Stock.sku, Stock.available)
    )
    
    updated = result.fetchone()
    if not updated:
        # Check if SKU exists
        stock = db.execute(
            select(Stock).where(Stock.sku == payload.sku)
        ).scalar_one_or_none()
        
        if not stock:
            raise HTTPException(
                status_code=404,
                detail=f"SKU '{payload.sku}' not found"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Insufficient stock for SKU '{payload.sku}'. Available: {stock.available}, Requested: {payload.quantity}"
            )
    
    # Create reservation record
    now = datetime.now(timezone.utc)
    reservation = Reservation(
        order_id=payload.order_id,
        sku=payload.sku,
        quantity=payload.quantity,
        status="active",
        expires_at=now + timedelta(minutes=payload.ttl_minutes)
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    
    # Update metrics
    STOCK_LEVEL.labels(sku=payload.sku).set(updated.available)
    _update_metrics(db)
    
    return ReserveResponse(
        reservation_id=reservation.id,
        order_id=reservation.order_id,
        sku=reservation.sku,
        quantity=reservation.quantity,
        status=reservation.status,
        expires_at=reservation.expires_at
    )


@app.post("/release", response_model=ReleaseResponse)
def release_reservation(payload: ReleaseRequest, db: Session = Depends(get_db)):
    """
    Release reservations for an order (e.g., on order cancellation or payment failure).
    Returns stock to available pool.
    """
    # Build query for active reservations
    query = select(Reservation).where(
        and_(
            Reservation.order_id == payload.order_id,
            Reservation.status == "active"
        )
    )
    if payload.sku:
        query = query.where(Reservation.sku == payload.sku)
    
    reservations = db.execute(query.with_for_update()).scalars().all()
    
    if not reservations:
        raise HTTPException(
            status_code=404,
            detail=f"No active reservations found for order {payload.order_id}"
        )
    
    released_count = 0
    released_quantity = 0
    now = datetime.now(timezone.utc)
    
    for reservation in reservations:
        # Return quantity to available stock
        db.execute(
            update(Stock)
            .where(Stock.sku == reservation.sku)
            .values(
                available=Stock.available + reservation.quantity,
                reserved=Stock.reserved - reservation.quantity
            )
        )
        
        # Mark reservation as released
        reservation.status = "released"
        reservation.released_at = now
        
        released_count += 1
        released_quantity += reservation.quantity
    
    db.commit()
    _update_metrics(db)
    
    return ReleaseResponse(
        released_count=released_count,
        released_quantity=released_quantity
    )


@app.post("/commit", response_model=CommitResponse)
def commit_reservation(payload: CommitRequest, db: Session = Depends(get_db)):
    """
    Commit reservations for an order (after successful payment).
    Stock is permanently deducted (reserved -> sold).
    """
    # Build query for active reservations
    query = select(Reservation).where(
        and_(
            Reservation.order_id == payload.order_id,
            Reservation.status == "active"
        )
    )
    if payload.sku:
        query = query.where(Reservation.sku == payload.sku)
    
    reservations = db.execute(query.with_for_update()).scalars().all()
    
    if not reservations:
        raise HTTPException(
            status_code=404,
            detail=f"No active reservations found for order {payload.order_id}"
        )
    
    committed_count = 0
    committed_quantity = 0
    now = datetime.now(timezone.utc)
    
    for reservation in reservations:
        # Reduce reserved count (stock already deducted from available)
        db.execute(
            update(Stock)
            .where(Stock.sku == reservation.sku)
            .values(reserved=Stock.reserved - reservation.quantity)
        )
        
        # Mark reservation as committed
        reservation.status = "committed"
        reservation.released_at = now
        
        committed_count += 1
        committed_quantity += reservation.quantity
    
    db.commit()
    _update_metrics(db)
    
    return CommitResponse(
        committed_count=committed_count,
        committed_quantity=committed_quantity
    )


@app.get("/reservations", response_model=list[ReserveResponse])
def list_reservations(
    order_id: Optional[int] = None,
    status: Optional[str] = Query(None, pattern="^(active|released|expired|committed)$"),
    db: Session = Depends(get_db)
):
    """List reservations with optional filters."""
    query = select(Reservation)
    
    if order_id:
        query = query.where(Reservation.order_id == order_id)
    if status:
        query = query.where(Reservation.status == status)
    
    reservations = db.execute(query.order_by(Reservation.created_at.desc())).scalars().all()
    
    return [
        ReserveResponse(
            reservation_id=r.id,
            order_id=r.order_id,
            sku=r.sku,
            quantity=r.quantity,
            status=r.status,
            expires_at=r.expires_at
        )
        for r in reservations
    ]


# ============== Seed Data ==============

@app.post("/seed")
def seed_stock(db: Session = Depends(get_db), _: dict = Depends(require_owner)):
    """Seed initial stock data for testing."""
    # Check if data already exists
    existing = db.execute(select(Stock)).first()
    if existing:
        return {"message": "Stock data already exists", "seeded": False}
    
    # Create sample stock items
    items = [
        Stock(sku="POSTER-SUNSET-A3", name="Sunset Poster A3", available=100),
        Stock(sku="POSTER-SUNSET-A2", name="Sunset Poster A2", available=50),
        Stock(sku="POSTER-SUNSET-A1", name="Sunset Poster A1", available=25),
        Stock(sku="POSTER-MOUNTAIN-A3", name="Mountain Poster A3", available=100),
        Stock(sku="POSTER-MOUNTAIN-A2", name="Mountain Poster A2", available=50),
        Stock(sku="POSTER-MOUNTAIN-A1", name="Mountain Poster A1", available=25),
        Stock(sku="FRAME-BLACK-A3", name="Black Frame A3", available=200),
        Stock(sku="FRAME-BLACK-A2", name="Black Frame A2", available=150),
        Stock(sku="FRAME-BLACK-A1", name="Black Frame A1", available=100),
        Stock(sku="FRAME-WOOD-A3", name="Wood Frame A3", available=150),
        Stock(sku="FRAME-WOOD-A2", name="Wood Frame A2", available=100),
        Stock(sku="FRAME-WOOD-A1", name="Wood Frame A1", available=75),
    ]
    
    db.add_all(items)
    db.commit()
    
    # Update metrics
    for item in items:
        STOCK_LEVEL.labels(sku=item.sku).set(item.available)
    
    return {"message": "Stock data seeded", "seeded": True, "items_created": len(items)}

