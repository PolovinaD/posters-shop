"""
Payment Service Mock - Simulates Stripe's Checkout Flow

This service mimics Stripe's behavior:
1. Create checkout sessions (like Stripe's /v1/checkout/sessions)
2. Simulate payment completion
3. Send signed webhooks to the orders service

In production, you'd use the actual Stripe SDK and receive real webhooks.
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from logger import get_logger, LoggingMiddleware

SERVICE_NAME = "payments"
logger = get_logger(__name__)

# Webhook secret - in production this would be from Stripe dashboard
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_key_12345")
ORDERS_WEBHOOK_URL = os.getenv("ORDERS_WEBHOOK_URL", "http://orders:8000/webhooks/stripe")


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
    success_url: str = "http://localhost:3000/success"
    cancel_url: str = "http://localhost:3000/cancel"


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


class CompleteSessionRequest(BaseModel):
    """Simulate card payment details (for testing)"""
    card_number: str = "4242424242424242"
    exp_month: int = 12
    exp_year: int = 2025
    cvc: str = "123"


# In-memory storage (in production, this would be Stripe's infrastructure)
sessions: dict[str, CheckoutSession] = {}

ROOT_PATH = os.getenv("ROOT_PATH", "")
app = FastAPI(title=f"{SERVICE_NAME} service (Stripe Mock)", root_path=ROOT_PATH)
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


def generate_session_id() -> str:
    """Generate Stripe-like session ID."""
    return f"cs_test_{secrets.token_hex(16)}"


def generate_payment_intent_id() -> str:
    """Generate Stripe-like payment intent ID."""
    return f"pi_test_{secrets.token_hex(16)}"


def generate_webhook_signature(payload: str, secret: str, timestamp: int) -> str:
    """
    Generate Stripe webhook signature.
    
    Stripe uses this format: t=timestamp,v1=signature
    The signature is HMAC-SHA256 of "timestamp.payload" with the webhook secret.
    """
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


async def send_webhook(event_type: str, data: dict):
    """
    Send a signed webhook to the orders service.
    
    This mimics exactly what Stripe does:
    1. Create the event payload
    2. Sign it with the webhook secret
    3. POST to the configured endpoint
    """
    event = {
        "id": f"evt_test_{secrets.token_hex(8)}",
        "object": "event",
        "api_version": "2023-10-16",
        "created": int(time.time()),
        "type": event_type,
        "data": {
            "object": data
        }
    }
    
    payload = json.dumps(event, separators=(',', ':'))
    timestamp = int(time.time())
    signature = generate_webhook_signature(payload, WEBHOOK_SECRET, timestamp)
    
    logger.info("Sending webhook", event_type=event_type, webhook_url=ORDERS_WEBHOOK_URL)
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                ORDERS_WEBHOOK_URL,
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "Stripe-Signature": signature
                }
            )
            if response.status_code == 200:
                logger.info("Webhook delivered successfully", event_type=event_type)
            else:
                logger.warning("Webhook delivery failed", status_code=response.status_code, response=response.text)
        except Exception as e:
            logger.error("Webhook error", error=str(e), event_type=event_type)


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
    Create a checkout session (mimics Stripe's API).
    
    In production with real Stripe:
    ```python
    session = stripe.checkout.Session.create(
        mode='payment',
        line_items=[...],
        success_url='...',
        cancel_url='...',
    )
    ```
    """
    session_id = generate_session_id()
    now = datetime.now(timezone.utc)
    
    # Calculate total
    amount_total = sum(item.unit_amount * item.quantity for item in payload.line_items)
    
    session = CheckoutSession(
        id=session_id,
        order_id=payload.order_id,
        customer_email=payload.customer_email,
        status=SessionStatus.OPEN,
        amount_total=amount_total,
        line_items=payload.line_items,
        checkout_url=f"http://localhost:8007/checkout/{session_id}",
        created_at=now,
        expires_at=now + timedelta(hours=24)  # 24h expiry
    )
    
    sessions[session_id] = session
    
    logger.info("Created checkout session", session_id=session_id, order_id=payload.order_id, checkout_url=session.checkout_url)
    
    return session


@app.get("/v1/checkout/sessions/{session_id}", response_model=CheckoutSession)
def get_session(session_id: str):
    """Get checkout session by ID."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


@app.get("/v1/checkout/sessions", response_model=list[CheckoutSession])
def list_sessions(
    order_id: Optional[int] = None,
    status: Optional[SessionStatus] = None
):
    """List checkout sessions with optional filters."""
    result = list(sessions.values())
    
    if order_id:
        result = [s for s in result if s.order_id == order_id]
    if status:
        result = [s for s in result if s.status == status]
    
    return result


# ============== Payment Simulation ==============

@app.post("/v1/checkout/sessions/{session_id}/complete")
async def complete_session(session_id: str, payment: CompleteSessionRequest = None):
    """
    Simulate a successful payment.
    
    In production, this would be Stripe's internal process after the customer
    submits their card details on Stripe's hosted checkout page.
    
    This endpoint:
    1. Validates the session
    2. Creates a payment intent
    3. Marks session as complete
    4. Sends webhook to the orders service
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status != SessionStatus.OPEN:
        raise HTTPException(
            status_code=400,
            detail=f"Session is already {session.status}"
        )
    
    # Simulate card validation (always succeeds with test card)
    if payment and payment.card_number.startswith("4000000000000002"):
        # Decline card number for testing failures
        raise HTTPException(status_code=402, detail="Card declined")
    
    # Create payment intent
    session.payment_intent_id = generate_payment_intent_id()
    session.status = SessionStatus.COMPLETE
    
    logger.info("Payment completed", session_id=session_id, amount_cents=session.amount_total, order_id=session.order_id)
    
    # Send webhook (async, like Stripe does)
    # In production, Stripe sends this automatically
    asyncio.create_task(
        send_webhook(
            "checkout.session.completed",
            {
                "id": session.id,
                "object": "checkout.session",
                "mode": "payment",
                "payment_status": "paid",
                "payment_intent": session.payment_intent_id,
                "amount_total": session.amount_total,
                "currency": session.currency,
                "customer_email": session.customer_email,
                "metadata": {
                    "order_id": str(session.order_id)
                }
            }
        )
    )
    
    return {
        "status": "success",
        "session_id": session_id,
        "payment_intent_id": session.payment_intent_id,
        "amount": session.amount_total,
        "message": "Payment successful. Webhook sent to orders service."
    }


@app.post("/v1/checkout/sessions/{session_id}/expire")
async def expire_session(session_id: str):
    """
    Simulate session expiration.
    
    Sends checkout.session.expired webhook.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status != SessionStatus.OPEN:
        raise HTTPException(status_code=400, detail=f"Session is {session.status}")
    
    session.status = SessionStatus.EXPIRED
    
    # Send expiration webhook
    asyncio.create_task(
        send_webhook(
            "checkout.session.expired",
            {
                "id": session.id,
                "object": "checkout.session",
                "payment_status": "unpaid",
                "metadata": {
                    "order_id": str(session.order_id)
                }
            }
        )
    )
    
    return {"status": "expired", "session_id": session_id}


# ============== Mock Checkout Page ==============

@app.get("/checkout/{session_id}")
def checkout_page(session_id: str):
    """
    Mock checkout page HTML.
    
    In production, this is Stripe's hosted checkout page.
    The customer never sees your backend - they interact directly with Stripe.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    if session.status != SessionStatus.OPEN:
        return {
            "status": session.status,
            "message": f"This checkout session is {session.status}"
        }
    
    return {
        "checkout_session": session_id,
        "order_id": session.order_id,
        "customer_email": session.customer_email,
        "amount": f"${session.amount_total / 100:.2f}",
        "items": [
            f"{item.quantity}x {item.name} (${item.unit_amount / 100:.2f})"
            for item in session.line_items
        ],
        "instructions": "To complete payment, POST to /v1/checkout/sessions/{session_id}/complete",
        "test_cards": {
            "success": "4242424242424242",
            "decline": "4000000000000002"
        }
    }


# ============== Webhook Secret (for testing) ==============

@app.get("/webhook-secret")
def get_webhook_secret():
    """
    Get the webhook secret for testing.
    
    In production, you'd get this from Stripe dashboard.
    NEVER expose this in production!
    """
    return {
        "webhook_secret": WEBHOOK_SECRET,
        "warning": "This is for testing only. Never expose in production!"
    }

