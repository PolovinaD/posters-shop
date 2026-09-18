import os
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from auth import get_current_user_claims

ROOT_PATH = os.getenv("ROOT_PATH", "")
READYZ_TIMEOUT_SECONDS = 2.0
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import Order, OrderItem, OrderStatus, PaymentMethod, EscrowStatus, SCHEMA_NAME
from schemas import (
    OrderCreate, OrderOut, OrderSummary,
    OrderItemOut, StatusTransition, CancelOrderResponse
)
from metrics import (
    metrics_endpoint, track_metrics,
    ORDERS_CREATED, ORDER_TOTAL_AMOUNT,
    INVENTORY_RESERVATION_FAILURES, SERVICE_NAME
)
from status_metrics import (
    init_orders_by_status, compute_orders_by_status, orders_by_status_worker
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
from payment_client import (
    PaymentServiceError, EscrowRejectedError, EscrowContractMissingError, EscrowUnavailableError
)
from order_paid import mark_order_paid, InvalidPaidTransition
from escrow_rules import WALLET_RE
from escrow_reconciler import escrow_reconciler_worker
import catalog_client
from catalog_client import CatalogServiceError, UnknownSkuError
from circuit_breaker import CircuitOpenError
from stripe_webhook import process_webhook, WebhookError
from logger import get_logger, LoggingMiddleware
from service_auth import require_service_or_owner
from auth import get_current_user_claims, require_owner

logger = get_logger(__name__)


# Pydantic models for payment endpoints
class CheckoutSessionResponse(BaseModel):
    checkout_session_id: str
    checkout_url: str
    order_id: int
    amount_total: int


# Pydantic models for escrow endpoints (phase 8)
class EscrowDeployResponse(BaseModel):
    order_id: int
    contract_address: str
    deploy_tx_hash: Optional[str] = None
    amount_wei: str
    invoice: dict
    config: dict


class EscrowStateResponse(BaseModel):
    order_id: int
    order_status: str
    payment_method: str
    escrow_status: Optional[str] = None
    contract_address: Optional[str] = None
    customer_wallet: Optional[str] = None
    courier_wallet: Optional[str] = None
    amount_wei: Optional[str] = None
    chain: Optional[dict] = None
    chain_error: Optional[str] = None


class CourierBindRequest(BaseModel):
    courier_wallet: str = Field(pattern=WALLET_RE)

# Background task control
outbox_task = None
status_task = None
escrow_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Startup - migrations should be run via 'alembic upgrade head' before starting
    logger.info("Service starting", note="Ensure migrations are applied via 'alembic upgrade head'")

    # Start outbox worker
    global outbox_task, status_task, escrow_task
    outbox_task = asyncio.create_task(outbox_worker(poll_interval=2.0))
    logger.info("Outbox worker started", poll_interval=2.0)

    # Publish all eight orders_by_status labels at 0 BEFORE the first scrape can
    # arrive, then keep them fresh on a timer. Every replica runs its own
    # refresher: the gauge describes global database state, so it must not depend
    # on which pod happened to serve a request.
    init_orders_by_status()
    status_task = asyncio.create_task(orders_by_status_worker(refresh_interval=15.0))
    logger.info("Orders-by-status refresher started", refresh_interval=15.0)

    # Escrow reconciler: marks paid orders whose browser died after paying and
    # retries deferred courier bindings / refunds. Idempotent per replica.
    escrow_task = asyncio.create_task(escrow_reconciler_worker())
    logger.info("Escrow reconciler started")

    yield

    # Shutdown
    if outbox_task:
        outbox_task.cancel()
        try:
            await outbox_task
        except asyncio.CancelledError:
            pass
    if status_task:
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass
    if escrow_task:
        escrow_task.cancel()
        try:
            await escrow_task
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
    # Price is resolved from the catalog, never taken from the request. What a
    # client sends is a proposal; the catalog owns the number that gets charged
    # and the one that later reaches Stripe.
    try:
        priced = await catalog_client.resolve_prices([i.sku for i in payload.items])
    except UnknownSkuError as e:
        logger.warning("Order rejected: unknown SKU", skus=e.skus)
        raise HTTPException(
            status_code=400, detail=f"Unknown or unavailable items: {', '.join(e.skus)}"
        )
    except CircuitOpenError:
        logger.warning("Order rejected: catalog circuit open")
        raise HTTPException(status_code=503, detail="Catalog service unavailable")
    except CatalogServiceError as e:
        logger.error("Order rejected: catalog unreachable", error=str(e))
        raise HTTPException(status_code=503, detail="Catalog service unavailable")

    total = sum(priced[i.sku]["price"] * i.quantity for i in payload.items)

    # Set customer_email from JWT sub — never trust client-supplied email
    customer_email = claims["sub"]

    # The address IS customer-supplied — unlike the e-mail there is no server-side
    # source to override it with, so it is validated by ShippingAddress instead.
    addr = payload.shipping_address

    # Every SQL statement runs in the request threadpool (run_in_threadpool):
    # a sync Session call on the event loop blocks every other request and
    # /healthz — the 2026-09-18 liveness-probe kills.
    def _insert() -> Order:
        # Create order
        order = Order(
            customer_email=customer_email,
            status=OrderStatus.CREATED,
            total_amount=total,
            shipping_recipient_name=addr.recipient_name,
            shipping_street=addr.street,
            shipping_city=addr.city,
            shipping_postal_code=addr.postal_code,
            shipping_country=addr.country,
            shipping_phone=addr.phone,
            payment_method=payload.payment_method,
            customer_wallet=payload.customer_wallet,
            escrow_status=(
                EscrowStatus.AWAITING_PAYMENT
                if payload.payment_method == PaymentMethod.ESCROW else None
            ),
        )
        db.add(order)
        db.flush()  # Get order ID

        # Add items, named and priced by the catalog
        for item in payload.items:
            resolved = priced[item.sku]
            order_item = OrderItem(
                order_id=order.id,
                sku=item.sku,
                name=resolved["name"],
                quantity=item.quantity,
                unit_price=resolved["price"],
            )
            db.add(order_item)

        db.flush()
        return order

    order = await run_in_threadpool(_insert)

    def _reserved() -> OrderOut:
        # All reservations successful - transition to RESERVED. The response
        # model is built here because it loads order.items (lazy relationship).
        order.status = OrderStatus.RESERVED
        db.commit()
        db.refresh(order)
        return OrderOut.model_validate(order)

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

        result = await run_in_threadpool(_reserved)

        # Update metrics
        ORDERS_CREATED.inc()
        ORDER_TOTAL_AMOUNT.observe(float(total))

        return result

    except InsufficientStockError as e:
        # Release any reservations we made
        for sku in reserved_items:
            try:
                await inventory_client.release_stock(order.id, sku)
            except InventoryServiceError:
                pass  # Best effort cleanup

        INVENTORY_RESERVATION_FAILURES.labels(reason="insufficient_stock").inc()
        await run_in_threadpool(db.rollback)
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
        await run_in_threadpool(db.rollback)
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
        await run_in_threadpool(db.rollback)
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
        await run_in_threadpool(db.rollback)
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
            item_count=len(o.items),
            payment_method=o.payment_method,
            escrow_status=o.escrow_status,
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
async def pay_order(
    order_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_owner),
):
    """
    Mark order as paid and commit inventory reservations.

    Owner-only. This is the synchronous path that bypasses Stripe entirely, so a
    customer must never reach it — marking your own order paid without paying is
    exactly the abuse it enables. Customers pay through POST /orders/{id}/checkout
    and Stripe's webhook. The admin dashboard is the only caller.

    Uses OUTBOX PATTERN: Instead of calling production directly,
    we emit an ORDER_PAID event to the outbox. The outbox worker
    will deliver this event reliably to the production service.
    
    This ensures the event is never lost, even if production is down.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not OrderStatus.can_transition(order.status, OrderStatus.PAID):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pay order in status '{order.status}'. Order must be in 'reserved' status."
        )

    def _paid() -> OrderOut:
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
        return OrderOut.model_validate(order)

    try:
        # Commit stock reservations (permanent deduction)
        await inventory_client.commit_stock(order_id)

        result = await run_in_threadpool(_paid)

        logger.info("Order paid - event emitted to outbox", order_id=order_id, event_type="ORDER_PAID")

        return result

    except CircuitOpenError:
        await run_in_threadpool(db.rollback)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="inventory service unavailable — circuit open"
        )

    except InventoryServiceError as e:
        await run_in_threadpool(db.rollback)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to commit inventory: {e}"
        )


@app.post("/orders/{order_id}/produce", response_model=OrderOut)
def start_production(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(require_service_or_owner)):
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
def ship_order(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(require_service_or_owner)):
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

    # Emit ORDER_SHIPPED event to outbox (SAME TRANSACTION!) so notifications
    # sends a "shipped" email. Delivered reliably via the outbox worker.
    items = [
        {"sku": i.sku, "name": i.name, "quantity": i.quantity}
        for i in order.items
    ]
    emit_event(
        db=db,
        event_type="ORDER_SHIPPED",
        aggregate_type="order",
        aggregate_id=str(order_id),
        payload={
            "order_id": order_id,
            "customer_email": order.customer_email,
            "status": order.status,
            "total_amount": str(order.total_amount),
            "items": items,
        }
    )

    db.commit()
    db.refresh(order)

    logger.info("Order shipped - event emitted", order_id=order_id, event_type="ORDER_SHIPPED")

    return order


@app.post("/orders/{order_id}/deliver", response_model=OrderOut)
def deliver_order(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(require_service_or_owner)):
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

    # Emit ORDER_DELIVERED event to outbox (SAME TRANSACTION!) so notifications
    # sends a "delivered" email. Delivered reliably via the outbox worker.
    items = [
        {"sku": i.sku, "name": i.name, "quantity": i.quantity}
        for i in order.items
    ]
    emit_event(
        db=db,
        event_type="ORDER_DELIVERED",
        aggregate_type="order",
        aggregate_id=str(order_id),
        payload={
            "order_id": order_id,
            "customer_email": order.customer_email,
            "status": order.status,
            "total_amount": str(order.total_amount),
            "items": items,
        }
    )

    db.commit()
    db.refresh(order)

    logger.info("Order delivered - event emitted", order_id=order_id, event_type="ORDER_DELIVERED")

    return order


@app.post("/orders/{order_id}/cancel", response_model=CancelOrderResponse)
async def cancel_order(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Cancel an order and release reserved stock.

    Can only cancel orders that haven't started production.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if claims.get("role") != "owner" and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")

    if not OrderStatus.can_cancel(order.status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in status '{order.status}'. Orders can only be cancelled before production starts."
        )

    # Escrow orders: refund the customer on chain BEFORE the order flips to
    # CANCELLED. Never cancel a funded escrow without refunding: the customer's
    # ether would be stranded in a contract nobody cancels.
    try:
        escrow_refunded = await _refund_escrow_if_open(order)
    except EscrowRejectedError as e:
        raise HTTPException(status_code=409, detail=e.reason)
    except (CircuitOpenError, PaymentServiceError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Escrow refund unavailable, try again: {e}",
        )

    # Capture the prior status BEFORE the mutation below: the outbox payload
    # reports what the order was cancelled *from*, and reading order.status after
    # the assignment always yields "cancelled". notifications keys the "this order
    # had already been paid" wording off this field.
    previous_status = order.status

    released_stock = False

    # If order was reserved, release the stock
    if previous_status == OrderStatus.RESERVED:
        try:
            result = await inventory_client.release_stock(order_id)
            released_stock = result.get("released_count", 0) > 0
        except InventoryServiceError:
            # Best effort - continue with cancellation
            pass

    def _cancel() -> CancelOrderResponse:
        order.status = OrderStatus.CANCELLED

        # Emit ORDER_CANCELLED event
        emit_event(
            db=db,
            event_type="ORDER_CANCELLED",
            aggregate_type="order",
            aggregate_id=str(order_id),
            payload={
                "order_id": order_id,
                "customer_email": order.customer_email,
                "previous_status": previous_status,
                "released_stock": released_stock,
                "escrow_refunded": escrow_refunded,
            }
        )

        db.commit()

        return CancelOrderResponse(
            order_id=order.id,
            status=order.status,
            released_stock=released_stock,
            message="Order cancelled successfully"
        )

    return await run_in_threadpool(_cancel)


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
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if claims.get("role") != "owner" and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")

    if order.payment_method == PaymentMethod.ESCROW:
        raise HTTPException(
            status_code=400,
            detail="Order uses escrow payment; use POST /orders/{id}/escrow"
        )

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
    
    # Create line items from order items (order.items is a lazy relationship)
    def _line_items() -> list:
        return [
            {
                "name": item.name,
                "quantity": item.quantity,
                "unit_amount": int(item.unit_price * 100)  # Convert to cents
            }
            for item in order.items
        ]

    line_items = await run_in_threadpool(_line_items)
    
    try:
        session = await payment_client.create_checkout_session(
            order_id=order_id,
            customer_email=order.customer_email,
            line_items=line_items
        )

        # Store session ID on order
        def _store() -> None:
            order.checkout_session_id = session["id"]
            db.commit()

        await run_in_threadpool(_store)
        
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
async def get_checkout_status(
    order_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(get_current_user_claims),
):
    """Get the status of an order's checkout session.

    Same visibility rule as GET /orders/{order_id}: owners and couriers may view
    any order, a customer only their own.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if claims.get("role") not in ("owner", "courier") and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")

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


# ============== Escrow payment ==============
#
# Orders is the source of truth for escrow state; payments stays stateless and
# only talks to the chain. Every payments call goes through payment_client and
# its circuit breaker. Contract require() refusals surface as 409 with the bare
# revert reason; a payments/chain outage as 503.

def _require_order_access(order: Order, claims: dict, allow_courier: bool = False) -> None:
    """403 rule copied from get_order (allow_courier) / create_checkout (owner or own order)."""
    roles = ("owner", "courier") if allow_courier else ("owner",)
    if claims.get("role") not in roles and order.customer_email != claims.get("sub"):
        raise HTTPException(status_code=403, detail="Access denied")


async def _refund_escrow_if_open(order: Order) -> bool:
    """Cancel the contract (refunding the customer if funded) for an escrow order still open on chain.

    Returns True if a cancel tx was sent. Raises EscrowRejectedError (caller maps
    409) or EscrowUnavailableError / CircuitOpenError / PaymentServiceError
    (caller maps 503).
    """
    if (
        order.payment_method != PaymentMethod.ESCROW
        or not order.escrow_contract_address
        or order.escrow_status not in EscrowStatus.OPEN
    ):
        return False
    result = await payment_client.cancel_escrow(order.escrow_contract_address)
    order.escrow_status = EscrowStatus.CANCELLED
    logger.info("Escrow contract cancelled", order_id=order.id, tx_hash=result.get("tx_hash"))
    return True


@app.post("/orders/{order_id}/escrow", response_model=EscrowDeployResponse)
async def create_escrow(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Start (or resume) an escrow payment: deploy the per-order OrderEscrow
    contract through payments exactly once and return what the browser needs
    to sign the pay() transaction (invoice + chain config).

    Mirrors POST /orders/{id}/checkout for card orders. Idempotent: a second
    call returns the stored contract without deploying again.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _require_order_access(order, claims)

    if order.payment_method != PaymentMethod.ESCROW:
        raise HTTPException(status_code=400, detail="Order is not an escrow order")

    if not order.escrow_contract_address:
        if order.status != OrderStatus.RESERVED:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start escrow payment for order in status '{order.status}'. Order must be in 'reserved' status."
            )
        if not order.customer_wallet:
            raise HTTPException(status_code=400, detail="Order has no customer wallet")
        try:
            deployed = await payment_client.create_escrow(
                order_id, order.customer_wallet, str(order.total_amount)
            )
        except CircuitOpenError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="payments service unavailable — circuit open"
            )
        except (EscrowUnavailableError, PaymentServiceError) as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Escrow unavailable: {e}"
            )
        def _store() -> None:
            order.escrow_contract_address = deployed["contract_address"]
            order.escrow_deploy_tx = deployed.get("deploy_tx_hash")
            order.escrow_amount_wei = str(deployed["amount_wei"])
            order.escrow_status = EscrowStatus.AWAITING_PAYMENT
            db.commit()
            db.refresh(order)  # the log and the response below read order.* after the commit

        await run_in_threadpool(_store)
        logger.info(
            "Escrow contract deployed",
            order_id=order_id,
            contract_address=order.escrow_contract_address,
            amount_wei=order.escrow_amount_wei,
        )

    try:
        invoice = await payment_client.get_escrow_invoice(order.escrow_contract_address)
        config = await payment_client.get_escrow_config()
    except CircuitOpenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payments service unavailable — circuit open"
        )
    except PaymentServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Escrow unavailable: {e}"
        )

    return EscrowDeployResponse(
        order_id=order.id,
        contract_address=order.escrow_contract_address,
        deploy_tx_hash=order.escrow_deploy_tx,
        amount_wei=order.escrow_amount_wei,
        invoice=invoice,
        config=config,
    )


@app.get("/orders/{order_id}/escrow", response_model=EscrowStateResponse)
async def get_escrow(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """Stored escrow state plus the live chain state. Visibility like GET /orders/{id}."""
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _require_order_access(order, claims, allow_courier=True)

    chain = None
    chain_error = None
    if order.escrow_contract_address:
        try:
            chain = await payment_client.get_escrow_state(order.escrow_contract_address)
        except (CircuitOpenError, PaymentServiceError) as e:
            chain_error = str(e)

    return EscrowStateResponse(
        order_id=order.id,
        order_status=order.status,
        payment_method=order.payment_method,
        escrow_status=order.escrow_status,
        contract_address=order.escrow_contract_address,
        customer_wallet=order.customer_wallet,
        courier_wallet=order.courier_wallet,
        amount_wei=order.escrow_amount_wei,
        chain=chain,
        chain_error=chain_error,
    )


@app.post("/orders/{order_id}/escrow/verify")
async def verify_escrow(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    Read the chain; when the contract is funded run the SAME mark_order_paid
    the Stripe webhook runs (commit stock, PAID, ORDER_PAID event). Idempotent.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _require_order_access(order, claims)

    if order.payment_method != PaymentMethod.ESCROW:
        raise HTTPException(status_code=400, detail="Order is not an escrow order")
    if not order.escrow_contract_address:
        raise HTTPException(status_code=400, detail="Escrow contract not deployed yet")

    if order.status == OrderStatus.PAID or (
        order.escrow_status in (EscrowStatus.FUNDED, EscrowStatus.IN_DELIVERY, EscrowStatus.RELEASED)
        and order.status != OrderStatus.RESERVED
    ):
        return {
            "status": "already_paid",
            "order_id": order_id,
            "order_status": order.status,
            "escrow_status": order.escrow_status,
        }

    try:
        chain = await payment_client.get_escrow_state(order.escrow_contract_address)
    except EscrowContractMissingError:
        def _fail() -> None:
            order.escrow_status = EscrowStatus.FAILED
            db.commit()
            db.refresh(order)  # the log below reads order.escrow_contract_address

        await run_in_threadpool(_fail)
        logger.error(
            "Escrow contract missing on chain",
            order_id=order_id, contract_address=order.escrow_contract_address,
        )
        raise HTTPException(status_code=409, detail="Escrow contract no longer exists on chain")
    except CircuitOpenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payments service unavailable — circuit open"
        )
    except PaymentServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Escrow unavailable: {e}"
        )

    chain_state = chain["state"]
    if chain_state in ("funded", "in_delivery", "released") and order.status == OrderStatus.RESERVED:
        # Set escrow_status BEFORE mark_order_paid so its single commit covers both.
        order.escrow_status = EscrowStatus.FUNDED if chain_state == "funded" else chain_state
        try:
            await mark_order_paid(db, order, payment_ref=order.escrow_contract_address)
        except InvalidPaidTransition as e:
            await run_in_threadpool(db.rollback)
            raise HTTPException(status_code=400, detail=str(e))
        logger.info("Escrow payment verified", order_id=order_id, chain_state=chain_state)
        return {
            "status": "paid",
            "order_id": order_id,
            "order_status": order.status,
            "escrow_status": order.escrow_status,
            "chain_state": chain_state,
        }

    return {
        "status": "awaiting_payment",
        "order_id": order_id,
        "order_status": order.status,
        "escrow_status": order.escrow_status,
        "chain_state": chain_state,
    }


@app.post("/orders/{order_id}/escrow/confirm-delivery")
async def confirm_escrow_delivery(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(get_current_user_claims)):
    """
    The customer confirms receipt: payments sends confirmDelivery() from the
    owner key and the contract pays the courier share and the owner remainder.
    Only for a DELIVERED order; the contract answers 409 "Delivery not
    complete." when no courier was ever bound.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    _require_order_access(order, claims)

    if order.payment_method != PaymentMethod.ESCROW:
        raise HTTPException(status_code=400, detail="Order is not an escrow order")
    if not order.escrow_contract_address:
        raise HTTPException(status_code=400, detail="Escrow contract not deployed yet")

    if order.escrow_status == EscrowStatus.RELEASED:
        return {"status": "already_released", "order_id": order_id, "escrow_status": EscrowStatus.RELEASED}

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot confirm receipt for order in status '{order.status}'. Order must be 'delivered'."
        )

    try:
        result = await payment_client.release_escrow(order.escrow_contract_address)
    except EscrowRejectedError as e:
        raise HTTPException(status_code=409, detail=e.reason)
    except CircuitOpenError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payments service unavailable — circuit open"
        )
    except (EscrowUnavailableError, PaymentServiceError) as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Escrow unavailable: {e}"
        )

    def _released() -> None:
        order.escrow_status = EscrowStatus.RELEASED
        db.commit()

    await run_in_threadpool(_released)
    logger.info("Escrow released", order_id=order_id, tx_hash=result.get("tx_hash"))
    return {
        "status": "released",
        "order_id": order_id,
        "escrow_status": EscrowStatus.RELEASED,
        "tx_hash": result.get("tx_hash"),
    }


@app.post("/internal/orders/{order_id}/courier")
async def bind_order_courier(
    order_id: int,
    payload: CourierBindRequest,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_service_or_owner),
):
    """
    CONTRACT B — called by logistics on courier pick-up (dispatched -> in_transit).

    Always HTTP 200 (idempotent, fire-and-forget caller):
      {"status": "bound" | "stored" | "already_bound" | "deferred" | "not_found",
       "order_id": <int>, "escrow_status": <str|null>}
    - not_found:     no such order
    - stored:        wallet saved; not an escrow order (or no contract yet)
    - already_bound: escrow_status already in_delivery/released
    - bound:         wallet saved AND assignCourier succeeded on chain -> in_delivery
    - deferred:      wallet saved but payments/chain unavailable or contract not
                     yet funded -> escrow_status unchanged; the reconciler retries
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if order is None:
        logger.info("Courier wallet for unknown order, no-op", order_id=order_id)
        return {"status": "not_found", "order_id": order_id, "escrow_status": None}

    order.courier_wallet = payload.courier_wallet

    def _answer(status_word: str) -> dict:
        # The commit step: order.escrow_status is re-read after the commit, in the threadpool.
        db.commit()
        return {"status": status_word, "order_id": order_id, "escrow_status": order.escrow_status}

    if order.payment_method != PaymentMethod.ESCROW or not order.escrow_contract_address:
        return await run_in_threadpool(_answer, "stored")
    if order.escrow_status in (EscrowStatus.IN_DELIVERY, EscrowStatus.RELEASED):
        return await run_in_threadpool(_answer, "already_bound")
    if order.escrow_status != EscrowStatus.FUNDED:
        # Not funded yet: the reconciler binds once the payment lands.
        return await run_in_threadpool(_answer, "deferred")

    try:
        await payment_client.assign_escrow_courier(order.escrow_contract_address, payload.courier_wallet)
    except EscrowRejectedError as e:
        # "Transfer not complete." = the chain lags the row; anything else is
        # logged. Either way the reconciler retries from the stored wallet.
        if e.reason != "Transfer not complete.":
            logger.warning("Courier binding rejected by contract", order_id=order_id, reason=e.reason)
        return await run_in_threadpool(_answer, "deferred")
    except (CircuitOpenError, PaymentServiceError) as e:
        logger.warning("Courier binding deferred: payments unavailable", order_id=order_id, error=str(e))
        return await run_in_threadpool(_answer, "deferred")

    def _bound() -> None:
        order.escrow_status = EscrowStatus.IN_DELIVERY
        db.commit()

    await run_in_threadpool(_bound)
    logger.info("Courier bound on chain", order_id=order_id, courier_wallet=payload.courier_wallet)
    return {"status": "bound", "order_id": order_id, "escrow_status": EscrowStatus.IN_DELIVERY}


# ============== Stripe Webhook ==============

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhooks.
    
    This endpoint receives events sent directly by Stripe:
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


# ============== Internal Service-to-Service ==============

@app.post("/internal/orders/{order_id}/reservation-expired")
async def reservation_expired(order_id: int, db: Session = Depends(get_db), claims: dict = Depends(require_service_or_owner)):
    """
    Internal endpoint called by the inventory service when a reservation
    expires. Auto-cancels the order if it is still in 'reserved' state.

    Idempotent contract — always returns 200:
      - order not found        -> {"status": "not_found", ...}
      - order not in RESERVED  -> {"status": "no_action", "current_status": ...}
      - order in RESERVED      -> flip to CANCELLED, emit ORDER_CANCELLED event

    No auth dependency: this is service-to-service over the cluster network.
    The inventory worker is fire-and-forget, so we deliberately avoid 4xx/5xx
    responses for the duplicate / unknown / wrong-state cases — they are
    expected and not errors.
    """
    order = await run_in_threadpool(db.get, Order, order_id)
    if order is None:
        logger.info("Reservation expired for unknown order, no-op", order_id=order_id)
        return {"status": "not_found", "order_id": order_id}

    if order.status != OrderStatus.RESERVED:
        logger.info(
            "Reservation expired but order not in reserved state, no-op",
            order_id=order_id,
            current_status=order.status,
        )
        return {
            "status": "no_action",
            "order_id": order_id,
            "current_status": order.status,
        }

    # Escrow orders: best-effort refund of an open contract. This endpoint must
    # always answer 200, so a failure here does NOT block the cancellation --
    # escrow_status then stays awaiting_payment/funded and the reconciler's
    # "refund" action retries until the contract is cancelled on chain.
    escrow_refunded = False
    try:
        escrow_refunded = await _refund_escrow_if_open(order)
    except Exception as e:
        logger.warning(
            "Escrow refund deferred on reservation expiry",
            order_id=order_id, error=str(e),
        )

    def _cancel() -> None:
        order.status = OrderStatus.CANCELLED
        emit_event(
            db=db,
            event_type="ORDER_CANCELLED",
            aggregate_type="order",
            aggregate_id=str(order_id),
            payload={
                "order_id": order_id,
                "customer_email": order.customer_email,
                "previous_status": "reserved",
                "reason": "reservation_expired",
                "released_stock": True,
                "escrow_refunded": escrow_refunded,
            },
        )
        db.commit()

    await run_in_threadpool(_cancel)
    logger.info(
        "Order auto-cancelled after reservation expiry",
        order_id=order_id,
    )
    return {"status": "cancelled", "order_id": order_id}


@app.get("/internal/orders/{order_id}/shipping-address")
def get_order_shipping_address(
    order_id: int,
    db: Session = Depends(get_db),
    claims: dict = Depends(require_service_or_owner),
):
    """Shipping address for one order, for the logistics service.

    Called exactly once per shipment, at shipment creation — logistics then keeps
    its own delivery copy, so no courier read ever depends on this service.
    GET /orders/{id} cannot serve this: its guard only admits owner/courier, and
    the caller holds a service token.
    """
    order = db.get(Order, order_id)
    if order is None:
        logger.warning("Shipping address requested for unknown order", order_id=order_id)
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order_id": order_id, "shipping_address": order.shipping_address}


# ============== Outbox Monitoring ==============

@app.get("/outbox/stats")
def outbox_stats(
    db: Session = Depends(get_db),
    claims: dict = Depends(require_owner),
):
    """Get outbox statistics for monitoring. Owner-only — operational internals
    (undelivered events, last_error strings) are not customer-facing."""
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
    """Get count of orders by status.

    The orders_by_status Prometheus gauge is NOT written here -- it describes
    global database state and is owned by status_metrics.orders_by_status_worker,
    which runs on every replica. Writing it from a request handler is what left
    the metric absent (rendering as "No data") on any pod that had never served
    this endpoint. See .planning/quick/260817-orders-status-gauge/.
    """
    return compute_orders_by_status(db)
