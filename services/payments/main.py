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
"""
import os
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logger import get_logger, LoggingMiddleware
from metrics import track_metrics, metrics_endpoint

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


ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title=f"{SERVICE_NAME} service (Stripe Hosted Checkout)", root_path=ROOT_PATH)
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
def create_checkout_session(payload: CreateSessionRequest):
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
