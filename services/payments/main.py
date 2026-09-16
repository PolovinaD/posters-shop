"""
Payment Service — Real Stripe Hosted Checkout

Integrates with the Stripe Hosted Checkout:
1. Creates checkout sessions via stripe.checkout.Session.create()
2. Returns the Stripe-hosted checkout URL to the caller
3. On payment, Stripe sends checkout.session.completed webhook to orders service directly

In production:
- STRIPE_SECRET_KEY must be set (live or test key from Stripe Dashboard)
- Register webhook URL in Stripe Dashboard: https://<ALB>/api/orders/webhooks/stripe
- STRIPE_WEBHOOK_SECRET must match the Stripe Dashboard webhook signing secret

Escrow (second provider, see escrow.py): the /v1/escrow/* endpoints drive a
per-order OrderEscrow contract on an Ethereum node. The chain is optional --
when it is unreachable those endpoints answer 503 and Stripe keeps working.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

import stripe
from fastapi import Depends, FastAPI, HTTPException, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from logger import get_logger, LoggingMiddleware
from service_auth import require_service_or_owner
from metrics import track_metrics, metrics_endpoint
import escrow
from escrow import EscrowNotFound, EscrowRevert, EscrowUnavailable

SERVICE_NAME = "payments"
logger = get_logger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_key_12345")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Set Stripe API key immediately — AuthenticationError on startup if key is missing/invalid
stripe.api_key = STRIPE_SECRET_KEY


class SessionStatus(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"
    EXPIRED = "expired"


class LineItem(BaseModel):
    name: str
    quantity: int
    unit_amount: int  # Amount in cents


class CreateSessionRequest(BaseModel):
    order_id: int
    customer_email: str
    line_items: list[LineItem]
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CheckoutSession(BaseModel):
    id: str
    order_id: int
    customer_email: str
    status: SessionStatus
    amount_total: int  # cents
    currency: str = "usd"
    line_items: list[LineItem]
    checkout_url: str
    created_at: datetime
    expires_at: datetime
    payment_intent_id: Optional[str] = None


ADDRESS_RE = r"^0x[0-9a-fA-F]{40}$"


class EscrowCreateRequest(BaseModel):
    order_id: int
    customer_address: str = Field(pattern=ADDRESS_RE)
    amount_usd: Decimal = Field(gt=0)


class EscrowCourierRequest(BaseModel):
    courier_address: str = Field(pattern=ADDRESS_RE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Escrow is optional: a missing/unreachable chain only disables /v1/escrow/*.
    # init_provider never raises; it logs and returns None. Run it off the loop so a
    # slow RPC timeout cannot delay Stripe readiness.
    await asyncio.to_thread(escrow.init_provider)
    yield


ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title=f"{SERVICE_NAME} service (Stripe Hosted Checkout)", root_path=ROOT_PATH, lifespan=lifespan)
app.add_middleware(LoggingMiddleware)

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

# CORS must be added after LoggingMiddleware so it wraps the outside (runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.middleware("http")(track_metrics)


@app.get("/metrics")
def metrics():
    return metrics_endpoint()


# ============== Health ==============

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz")
def readyz():
    return {"status": "ready"}


# ============== Checkout Sessions ==============

@app.post("/v1/checkout/sessions", response_model=CheckoutSession)
def create_checkout_session(payload: CreateSessionRequest, claims: dict = Depends(require_service_or_owner)):
    """
    Create a real Stripe Hosted Checkout session.
    The customer is redirected to Stripe's hosted page to enter card details.
    On payment, Stripe sends checkout.session.completed webhook to orders service directly.
    """
    success_url = payload.success_url or f"{FRONTEND_URL}/shop/orders/{payload.order_id}"
    cancel_url = payload.cancel_url or f"{FRONTEND_URL}/shop"

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {"name": item.name},
                        "unit_amount": item.unit_amount,  # already in cents
                    },
                    "quantity": item.quantity,
                }
                for item in payload.line_items
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"order_id": str(payload.order_id)},
            customer_email=payload.customer_email,
        )
    except stripe.error.AuthenticationError as e:
        logger.error("Stripe authentication failed — check STRIPE_SECRET_KEY", error=str(e))
        raise HTTPException(status_code=503, detail="Payment service unavailable")
    except stripe.error.StripeError as e:
        logger.error("Stripe API error", error=str(e))
        raise HTTPException(status_code=502, detail=f"Stripe error: {str(e)}")

    now = datetime.now(timezone.utc)

    # Map session.url → checkout_url to preserve API surface consumed by orders service
    result = CheckoutSession(
        id=session.id,
        order_id=payload.order_id,
        customer_email=payload.customer_email,
        status=SessionStatus.OPEN,
        amount_total=session.amount_total or sum(
            item.unit_amount * item.quantity for item in payload.line_items
        ),
        line_items=payload.line_items,
        checkout_url=session.url,   # CRITICAL: Stripe uses .url not .checkout_url
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )

    logger.info("Created Stripe checkout session",
                session_id=session.id,
                order_id=payload.order_id,
                checkout_url=session.url)
    return result


@app.get("/v1/checkout/sessions", response_model=list[CheckoutSession])
def list_sessions():
    """
    List sessions endpoint — kept for API compatibility.
    In production with real Stripe, session listing requires Stripe API calls.
    Returns empty list as sessions are managed by Stripe.
    """
    return []


@app.get("/v1/checkout/sessions/{session_id}", response_model=CheckoutSession)
def get_session(session_id: str):
    """
    Get checkout session by ID — fetches from Stripe API.
    """
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session not found")
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {str(e)}")

    now = datetime.now(timezone.utc)
    return CheckoutSession(
        id=session.id,
        order_id=int(session.metadata.get("order_id", 0)),
        customer_email=session.customer_email or "",
        status=SessionStatus(session.status) if session.status in SessionStatus._value2member_map_ else SessionStatus.OPEN,
        amount_total=session.amount_total or 0,
        line_items=[],
        checkout_url=session.url or "",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )


# ============== Dev/Test Convenience Endpoints ==============

@app.post("/v1/checkout/sessions/{session_id}/complete")
async def complete_session(session_id: str):
    """
    Dev/test only: simulate payment completion for local dev without real Stripe.
    In production, Stripe sends checkout.session.completed webhook to orders service directly.
    Register webhook URL in Stripe Dashboard: https://<ALB>/api/orders/webhooks/stripe
    """
    logger.warning("complete_session called — dev/test only endpoint",
                   session_id=session_id)
    return {
        "status": "dev_only",
        "message": "In production, Stripe sends webhooks directly to orders service. "
                   "Register https://<ALB>/api/orders/webhooks/stripe in Stripe Dashboard.",
        "session_id": session_id,
    }


@app.post("/v1/checkout/sessions/{session_id}/expire")
async def expire_session(session_id: str):
    """
    Dev/test only: simulate session expiration.
    In production, Stripe handles this automatically after 24 hours.
    """
    logger.warning("expire_session called — dev/test only endpoint",
                   session_id=session_id)
    return {
        "status": "dev_only",
        "message": "In production, Stripe expires sessions automatically. "
                   "checkout.session.expired webhook is sent to orders service.",
        "session_id": session_id,
    }


# ============== Escrow ==============
#
# All handlers are plain `def`: web3 is synchronous, and FastAPI runs sync
# handlers in its threadpool so the event loop is never blocked by an RPC.
# /config and /demo-accounts are public reads (the SPA calls them before login)
# and are declared BEFORE the {address} routes; the address pattern keeps
# "config" from ever matching {address}. Everything else carries the same guard
# as /v1/checkout/sessions (orders calls with a service token; the owner by hand).

def _escrow_call(fn, *args):
    """Run a provider operation and translate its failures into HTTP."""
    try:
        return fn(*args)
    except EscrowRevert as e:
        logger.warning("Escrow contract rejected the call", reason=e.reason)
        raise HTTPException(status_code=409, detail=e.reason)
    except EscrowNotFound as e:
        raise HTTPException(status_code=404, detail=f"No escrow contract at {e}")
    except EscrowUnavailable as e:
        logger.error("Escrow chain unavailable", error=str(e))
        raise HTTPException(status_code=503, detail=f"Escrow unavailable: {e}")


def _provider():
    try:
        return escrow.get_provider()
    except EscrowUnavailable as e:
        raise HTTPException(status_code=503, detail=f"Escrow unavailable: {e}")


@app.get("/v1/escrow/config")
def escrow_config():
    """Public: what the SPA needs to offer (or hide) the Ether payment option."""
    base = {
        "rpc_url": escrow.ESCROW_PUBLIC_RPC_URL,
        "wei_per_usd": escrow.WEI_PER_USD,
        "courier_share_bps": escrow.ESCROW_COURIER_SHARE_BPS,
    }
    try:
        p = escrow.get_provider()
        return {**base, "enabled": True, "chain_id": p.chain_id(), "owner_address": p.owner_address}
    except EscrowUnavailable:
        return {**base, "enabled": False, "chain_id": None, "owner_address": None}


@app.get("/v1/escrow/demo-accounts")
def escrow_demo_accounts():
    """Public: Ganache's deterministic demo accounts for the checkout page.

    Double gate: the flag AND the node must identify as Ganache, so this can
    never serve keys on a real network.
    """
    if not escrow.ESCROW_EXPOSE_DEMO_ACCOUNTS:
        raise HTTPException(status_code=404, detail="Demo accounts are not exposed")
    p = _provider()
    if not p.is_ganache():
        raise HTTPException(status_code=404, detail="Demo accounts exist only on Ganache")
    return escrow.demo_accounts()


@app.post("/v1/escrow")
def escrow_create(payload: EscrowCreateRequest, claims: dict = Depends(require_service_or_owner)):
    """Deploy one OrderEscrow contract for an order; the owner key pays the gas."""
    p = _provider()
    result = _escrow_call(p.deploy, payload.order_id, payload.customer_address, str(payload.amount_usd))
    logger.info("Escrow contract deployed",
                order_id=payload.order_id,
                contract_address=result["contract_address"],
                amount_wei=result["amount_wei"])
    return result


@app.get("/v1/escrow/{address}")
def escrow_state(address: str = Path(pattern=ADDRESS_RE), claims: dict = Depends(require_service_or_owner)):
    return _escrow_call(_provider().state, address)


@app.get("/v1/escrow/{address}/invoice")
def escrow_invoice(address: str = Path(pattern=ADDRESS_RE), claims: dict = Depends(require_service_or_owner)):
    """The unsigned pay() transaction the customer's wallet signs and sends."""
    return _escrow_call(_provider().invoice, address)


@app.post("/v1/escrow/{address}/courier")
def escrow_assign_courier(payload: EscrowCourierRequest, address: str = Path(pattern=ADDRESS_RE),
                          claims: dict = Depends(require_service_or_owner)):
    result = _escrow_call(_provider().assign_courier, address, payload.courier_address)
    logger.info("Escrow courier bound", contract_address=address,
                courier_address=payload.courier_address, tx_hash=result["tx_hash"])
    return result


@app.post("/v1/escrow/{address}/release")
def escrow_release(address: str = Path(pattern=ADDRESS_RE), claims: dict = Depends(require_service_or_owner)):
    """confirmDelivery(): pays the courier share and the owner the rest, closes the contract."""
    result = _escrow_call(_provider().release, address)
    logger.info("Escrow released", contract_address=address, tx_hash=result["tx_hash"])
    return result


@app.post("/v1/escrow/{address}/cancel")
def escrow_cancel(address: str = Path(pattern=ADDRESS_RE), claims: dict = Depends(require_service_or_owner)):
    """cancel(): refunds the customer if funded, closes the contract."""
    result = _escrow_call(_provider().cancel, address)
    logger.info("Escrow cancelled", contract_address=address, tx_hash=result["tx_hash"])
    return result
