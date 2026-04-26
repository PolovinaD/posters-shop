import os
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from auth import get_current_user_claims

ROOT_PATH = os.getenv("ROOT_PATH", "")
from pydantic import BaseModel
from sqlalchemy import select, func as sql_func, text
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Order, OrderItem, OrderStatus, SCHEMA_NAME
from schemas import (
    OrderCreate, OrderOut, OrderSummary,
    OrderItemOut, StatusTransition, CancelOrderResponse
)
from metrics import (
    metrics_endpoint, track_metrics,
    ORDERS_CREATED, ORDERS_BY_STATUS, ORDER_TOTAL_AMOUNT,
    INVENTORY_RESERVATION_FAILURES, SERVICE_NAME
)
import inventory_client
from inventory_client import (
    InsufficientStockError, SkuNotFoundError, InventoryServiceError
)
from outbox import (
    OutboxEvent, emit_event, outbox_worker,
    get_pending_event_count, get_failed_event_count
)
import payment_client
from payment_client import PaymentServiceError
from circuit_breaker import CircuitOpenError
from stripe_webhook import process_webhook, WebhookError
from logger import get_logger, LoggingMiddleware
from auth import get_current_user_claims

logger = get_logger(__name__)


# Pydantic models for payment endpoints
class CheckoutSessionResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
    order_id: int
    amount_total: int

# Background task control
outbox_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup - migrations should be run via 'alembic upgrade head' before starting
    logger.info("Service starting", note="Ensure migrations are applied via 'alembic upgrade head'")
    
    # Start outbox worker
    global outbox_task
    outbox_task = asyncio.create_task(outbox_worker(poll_interval=2.0))
    logger.info("Outbox worker started", poll_interval=2.0)
    
    yield
    
    # Shutdown
    if outbox_task:
        outbox_task.cancel()
        try:
            await outbox_task
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


# ============== Order CRUD ==============

@app.post("/orders", response_model=OrderOut, status_code=201)
async def create_order(payload: OrderCreate, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Create a new order and reserve stock from inventory.

    Flow:
    1. Create order in CREATED status
    2. Reserve stock for each item in inventory service
    3. If all reservations succeed, transition to RESERVED status
    4. If any reservation fails, release previous reservations and fail the order
    """
    # Calculate total
    total = sum(item.unit_price * item.quantity for item in payload.items)

    # Set customer_email from JWT sub — never trust client-supplied email
    customer_email = claims["sub"]

    # Create order
    order = Order(
        customer_email=customer_email,
        status=OrderStatus.CREATED,
        total_amount=total
    )
    db.add(order)
    db.flush()  # Get order ID
    
    # Add items
    for item in payload.items:
        order_item = OrderItem(
            order_id=order.id,
            sku=item.sku,
            name=item.name,
            quantity=item.quantity,
            unit_price=item.unit_price
        )
        db.add(order_item)
    
    db.flush()
    
    # Reserve stock for each item
    reserved_items = []
    try:
        for item in payload.items:
            await inventory_client.reserve_stock(
                order_id=order.id,
                sku=item.sku,
                quantity=item.quantity,
                ttl_minutes=15  # 15 minute reservation TTL
            )
            reserved_items.append(item.sku)
        
        # All reservations successful - transition to RESERVED
        order.status = OrderStatus.RESERVED
        db.commit()
        db.refresh(order)
        
        # Update metrics
        ORDERS_CREATED.inc()
        ORDER_TOTAL_AMOUNT.observe(float(total))
        
        return order
        
    except InsufficientStockError as e:
        # Release any reservations we made
        for sku in reserved_items:
            try:
                await inventory_client.release_stock(order.id, sku)
            except InventoryServiceError:
                pass  # Best effort cleanup
        
        INVENTORY_RESERVATION_FAILURES.labels(reason="insufficient_stock").inc()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Insufficient stock for {e.sku}"
        )
        
    except SkuNotFoundError as e:
        # Release any reservations we made
        for sku in reserved_items:
            try:
                await inventory_client.release_stock(order.id, sku)
            except InventoryServiceError:
                pass
        
        INVENTORY_RESERVATION_FAILURES.labels(reason="sku_not_found").inc()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SKU not found: {e.sku}"
        )
        
    except CircuitOpenError:
        # Release any reservations we made
        for sku in reserved_items:
            try:
                await inventory_client.release_stock(order.id, sku)
            except Exception:
                pass
        INVENTORY_RESERVATION_FAILURES.labels(reason="circuit_open").inc()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inventory service unavailable — circuit open"
        )

    except InventoryServiceError as e:
        # Release any reservations we made
        for sku in reserved_items:
            try:
                await inventory_client.release_stock(order.id, sku)
            except InventoryServiceError:
                pass

        INVENTORY_RESERVATION_FAILURES.labels(reason="service_error").inc()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Inventory service unavailable: {e}"
        )


@app.get("/orders", response_model=list[OrderSummary])
def list_orders(
    status: Optional[str] = None,
    customer_email: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    """List orders with optional filters."""
    query = select(Order)

    if status:
        query = query.where(Order.status == status)

    if claims.get("role") in ("owner", "courier"):
        # Owners and couriers see all orders; apply optional customer_email filter if provided
        if customer_email:
            query = query.where(Order.customer_email == customer_email)
    else:
        # Customers only see their own orders — ignore any caller-supplied filter
        query = query.where(Order.customer_email == claims["sub"])
    
    query = query.order_by(Order.created_at.desc()).offset(skip).limit(limit)
    orders = db.execute(query).scalars().all()
    
    return [
        OrderSummary(
            id=o.id,
            customer_email=o.customer_email,
            status=o.status,
            total_amount=o.total_amount,
            created_at=o.created_at,
            item_count=len(o.items)
        )
        for o in orders
    ]


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """Get order by ID with all items. Requires auth; customer can only view their own orders."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Owners and couriers can view any order; customers can only view their own
    if claims.get("role") not in ("owner", "courier") and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")
    return order


# ============== Order State Transitions ==============

@app.post("/orders/{order_id}/pay", response_model=OrderOut)
async def pay_order(order_id: int, db: Session = Depends(get_db)):
    """
    Mark order as paid and commit inventory reservations.
    
    Uses OUTBOX PATTERN: Instead of calling production directly,
    we emit an ORDER_PAID event to the outbox. The outbox worker
    will deliver this event reliably to the production service.
    
    This ensures the event is never lost, even if production is down.
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not OrderStatus.can_transition(order.status, OrderStatus.PAID):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pay order in status '{order.status}'. Order must be in 'reserved' status."
        )
    
    try:
        # Commit stock reservations (permanent deduction)
        await inventory_client.commit_stock(order_id)
        
        # Update order status
        order.status = OrderStatus.PAID
        
        # Emit ORDER_PAID event to outbox (SAME TRANSACTION!)
        # This guarantees the event is persisted if and only if the order update succeeds
        items = [
            {"sku": item.sku, "name": item.name, "quantity": item.quantity}
            for item in order.items
        ]
        emit_event(
            db=db,
            event_type="ORDER_PAID",
            aggregate_type="order",
            aggregate_id=str(order_id),
            payload={
                "order_id": order_id,
                "customer_email": order.customer_email,
                "total_amount": str(order.total_amount),
                "items": items
            }
        )
        
        # Commit both the order update AND the outbox event atomically
        db.commit()
        db.refresh(order)
        
        logger.info("Order paid - event emitted to outbox", order_id=order_id, event_type="ORDER_PAID")
        
        return order
        
    except CircuitOpenError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inventory service unavailable — circuit open"
        )

    except InventoryServiceError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to commit inventory: {e}"
        )


@app.post("/orders/{order_id}/produce", response_model=OrderOut)
def start_production(order_id: int, db: Session = Depends(get_db)):
    """Mark order as in production."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not OrderStatus.can_transition(order.status, OrderStatus.PRODUCING):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start production for order in status '{order.status}'. Order must be in 'paid' status."
        )
    
    order.status = OrderStatus.PRODUCING
    db.commit()
    db.refresh(order)
    return order


@app.post("/orders/{order_id}/ship", response_model=OrderOut)
def ship_order(order_id: int, db: Session = Depends(get_db)):
    """Mark order as shipped."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not OrderStatus.can_transition(order.status, OrderStatus.SHIPPED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot ship order in status '{order.status}'. Order must be in 'producing' status."
        )
    
    order.status = OrderStatus.SHIPPED
    db.commit()
    db.refresh(order)
    return order


@app.post("/orders/{order_id}/deliver", response_model=OrderOut)
def deliver_order(order_id: int, db: Session = Depends(get_db)):
    """Mark order as delivered."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not OrderStatus.can_transition(order.status, OrderStatus.DELIVERED):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as delivered order in status '{order.status}'. Order must be in 'shipped' status."
        )
    
    order.status = OrderStatus.DELIVERED
    db.commit()
    db.refresh(order)
    return order


@app.post("/orders/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Cancel an order and release reserved stock.

    Can only cancel orders that haven't started production.
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if claims.get("role") != "owner" and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")

    if not OrderStatus.can_cancel(order.status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status '{order.status}'. Orders can only be cancelled before production starts."
        )
    
    released_stock = False
    
    # If order was reserved, release the stock
    if order.status == OrderStatus.RESERVED:
        try:
            result = await inventory_client.release_stock(order_id)
            released_stock = result.get("released_count", 0) > 0
        except InventoryServiceError:
            # Best effort - continue with cancellation
            pass
    
    order.status = OrderStatus.CANCELLED
    
    # Emit ORDER_CANCELLED event
    emit_event(
        db=db,
        event_type="ORDER_CANCELLED",
        aggregate_type="order",
        aggregate_id=str(order_id),
        payload={
            "order_id": order_id,
            "previous_status": order.status,
            "released_stock": released_stock
        }
    )
    
    db.commit()
    
    return CancelOrderResponse(
        order_id=order.id,
        status=order.status,
        released_stock=released_stock,
        message="Order cancelled successfully"
    )


# ============== Payment / Checkout ==============

@app.post("/orders/{order_id}/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Create a Stripe checkout session for an order.

    This is what happens when the customer clicks "Pay Now":
    1. Create a checkout session with Stripe
    2. Return the checkout URL to redirect the customer
    3. Customer pays on Stripe's hosted checkout
    4. Stripe sends webhook to /webhooks/stripe
    5. Webhook handler marks order as paid
    """
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if claims.get("role") != "owner" and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")

    if order.status != OrderStatus.RESERVED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot checkout order in status '{order.status}'. Order must be in 'reserved' status."
        )
    
    # If we already have a checkout session, return it
    if order.checkout_session_id:
        try:
            session = await payment_client.get_checkout_session(order.checkout_session_id)
            if session.get("status") == "open":
                return CheckoutSessionResponse(
                    checkout_session_id=session["id"],
                    checkout_url=session["checkout_url"],
                    order_id=order_id,
                    amount_total=session["amount_total"]
                )
        except PaymentServiceError:
            pass  # Session expired or invalid, create new one
    
    # Create line items from order items
    line_items = [
        {
            "name": item.name,
            "quantity": item.quantity,
            "unit_amount": int(item.unit_price * 100)  # Convert to cents
        }
        for item in order.items
    ]
    
    try:
        session = await payment_client.create_checkout_session(
            order_id=order_id,
            customer_email=order.customer_email,
            line_items=line_items
        )
        
        # Store session ID on order
        order.checkout_session_id = session["id"]
        db.commit()
        
        logger.info("Checkout session created", order_id=order_id, session_id=session["id"])
        
        return CheckoutSessionResponse(
            checkout_session_id=session["id"],
            checkout_url=session["checkout_url"],
            order_id=order_id,
            amount_total=session["amount_total"]
        )
        
    except CircuitOpenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payments service unavailable — circuit open"
        )

    except PaymentServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Payment service unavailable: {e}"
        )


@app.get("/orders/{order_id}/checkout-status")
async def get_checkout_status(order_id: int, db: Session = Depends(get_db)):
    """Get the status of an order's checkout session."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if not order.checkout_session_id:
        return {
            "order_id": order_id,
            "order_status": order.status,
            "checkout_session": None
        }
    
    try:
        session = await payment_client.get_checkout_session(order.checkout_session_id)
        return {
            "order_id": order_id,
            "order_status": order.status,
            "checkout_session": {
                "id": session["id"],
                "status": session["status"],
                "amount_total": session["amount_total"],
                "payment_intent_id": session.get("payment_intent_id")
            }
        }
    except CircuitOpenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payments service unavailable — circuit open"
        )

    except PaymentServiceError as e:
        return {
            "order_id": order_id,
            "order_status": order.status,
            "checkout_session": None,
            "error": str(e)
        }


# ============== Stripe Webhook ==============

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhooks.
    
    This endpoint receives events from Stripe (or our mock payment service):
    - checkout.session.completed: Payment successful
    - checkout.session.expired: Checkout session expired
    
    Security:
    - Verifies the Stripe-Signature header
    - Uses the webhook secret to validate authenticity
    
    In production, ALWAYS verify webhooks!
    """
    # Get raw body for signature verification
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    
    try:
        result = await process_webhook(payload, signature, db)
        return result
    except WebhookError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============== Outbox Monitoring ==============

@app.get("/outbox/stats")
def outbox_stats(db: Session = Depends(get_db)):
    """Get outbox statistics for monitoring."""
    pending = get_pending_event_count(db)
    failed = get_failed_event_count(db)
    
    # Get recent events
    recent = db.execute(
        select(OutboxEvent)
        .order_by(OutboxEvent.created_at.desc())
        .limit(10)
    ).scalars().all()
    
    return {
        "pending_count": pending,
        "failed_count": failed,
        "recent_events": [
            {
                "id": e.id,
                "event_type": e.event_type,
                "aggregate_id": e.aggregate_id,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "delivered_at": e.delivered_at.isoformat() if e.delivered_at else None,
                "retry_count": e.retry_count,
                "last_error": e.last_error
            }
            for e in recent
        ]
    }


# ============== Admin/Debug Endpoints ==============

@app.get("/orders/stats/by-status")
def orders_by_status(
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """Get count of orders by status."""
    result = db.execute(
        select(Order.status, sql_func.count(Order.id))
        .group_by(Order.status)
    ).all()
    
    stats = {status: count for status, count in result}
    
    # Update Prometheus metrics
    for status_val in [OrderStatus.CREATED, OrderStatus.RESERVED, OrderStatus.PAID,
                       OrderStatus.PRODUCING, OrderStatus.SHIPPED, OrderStatus.DELIVERED,
                       OrderStatus.CANCELLED, OrderStatus.FAILED]:
        ORDERS_BY_STATUS.labels(status=status_val).set(stats.get(status_val, 0))
    
    return stats
