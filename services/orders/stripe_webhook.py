"""
Stripe Webhook Handler

Handles incoming webhooks from Stripe (or our mock payment service).

Key concepts:
1. SIGNATURE VERIFICATION - All webhooks must be verified using the webhook secret
2. IDEMPOTENCY - Events may be sent multiple times, handlers must be idempotent
3. QUICK RESPONSE - Respond 200 quickly, do processing async or via outbox
"""
import hashlib
import hmac
import json
import os
import time
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from models import Order, OrderStatus
from outbox import emit_event
import inventory_client
from logger import get_logger

logger = get_logger("webhook")

# Webhook secret - must match the payment service
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_key_12345")

# Tolerance for timestamp verification (5 minutes)
TIMESTAMP_TOLERANCE = 300


class WebhookError(Exception):
    """Raised when webhook processing fails."""
    pass


def verify_stripe_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify Stripe webhook signature.
    
    Stripe signature format: t=timestamp,v1=signature,v1=signature2,...
    
    We verify by:
    1. Extracting the timestamp
    2. Checking it's not too old (replay attack prevention)
    3. Computing HMAC-SHA256 of "timestamp.payload"
    4. Comparing with provided signature(s)
    """
    if not signature:
        return False
    
    # Parse signature header
    elements = {}
    for item in signature.split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            if key in elements:
                if isinstance(elements[key], list):
                    elements[key].append(value)
                else:
                    elements[key] = [elements[key], value]
            else:
                elements[key] = value
    
    timestamp_str = elements.get("t")
    signatures = elements.get("v1")
    
    if not timestamp_str or not signatures:
        return False
    
    # Ensure signatures is a list
    if isinstance(signatures, str):
        signatures = [signatures]
    
    # Verify timestamp is not too old
    try:
        timestamp = int(timestamp_str)
    except ValueError:
        return False
    
    if abs(time.time() - timestamp) > TIMESTAMP_TOLERANCE:
        logger.warning("Webhook timestamp too old", timestamp=timestamp, tolerance_sec=TIMESTAMP_TOLERANCE)
        return False
    
    # Compute expected signature
    signed_payload = f"{timestamp}.{payload.decode()}"
    expected_sig = hmac.new(
        secret.encode(),
        signed_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Compare using constant-time comparison
    return any(hmac.compare_digest(expected_sig, sig) for sig in signatures)


def parse_webhook_event(payload: bytes) -> dict:
    """Parse and validate webhook event structure."""
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise WebhookError("Invalid JSON payload")
    
    # Validate required fields
    required = ["id", "type", "data"]
    if not all(key in event for key in required):
        raise WebhookError(f"Missing required fields: {required}")
    
    if "object" not in event.get("data", {}):
        raise WebhookError("Missing data.object in event")
    
    return event


async def handle_checkout_session_completed(
    event_data: dict,
    db: Session
) -> dict:
    """
    Handle checkout.session.completed event.
    
    This is called when a customer successfully pays.
    
    Flow:
    1. Extract order_id from metadata
    2. Verify order exists and is in correct state
    3. Commit inventory reservations
    4. Emit ORDER_PAID event to outbox
    """
    session = event_data.get("object", {})
    metadata = session.get("metadata", {})
    
    order_id_str = metadata.get("order_id")
    if not order_id_str:
        raise WebhookError("Missing order_id in session metadata")
    
    try:
        order_id = int(order_id_str)
    except ValueError:
        raise WebhookError(f"Invalid order_id: {order_id_str}")
    
    # Get order
    order = db.get(Order, order_id)
    if not order:
        raise WebhookError(f"Order {order_id} not found")
    
    # Idempotency check - if already paid, just return success
    if order.status == OrderStatus.PAID:
        logger.info("Order already paid (idempotent)", order_id=order_id)
        return {"status": "already_processed", "order_id": order_id}
    
    # Validate state transition
    if not OrderStatus.can_transition(order.status, OrderStatus.PAID):
        raise WebhookError(
            f"Cannot transition order {order_id} from {order.status} to paid"
        )
    
    # Commit inventory reservations
    try:
        await inventory_client.commit_stock(order_id)
    except Exception as e:
        # If inventory commit fails, we need to handle this carefully
        # In production, you might retry or alert
        logger.warning("Failed to commit inventory, continuing with payment", order_id=order_id, error=str(e))
        # Continue anyway - the payment succeeded, we need to honor it
    
    # Update order status
    order.status = OrderStatus.PAID
    order.payment_intent_id = session.get("payment_intent")
    
    # Emit ORDER_PAID event to outbox
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
            "payment_intent": session.get("payment_intent"),
            "items": items
        }
    )
    
    db.commit()
    
    logger.info("Order marked as paid via webhook", order_id=order_id, payment_intent=session.get("payment_intent"))
    
    return {
        "status": "processed",
        "order_id": order_id,
        "payment_intent": session.get("payment_intent")
    }


async def handle_checkout_session_expired(
    event_data: dict,
    db: Session
) -> dict:
    """
    Handle checkout.session.expired event.
    
    This is called when a checkout session expires without payment.
    We should release the reserved inventory.
    """
    session = event_data.get("object", {})
    metadata = session.get("metadata", {})
    
    order_id_str = metadata.get("order_id")
    if not order_id_str:
        raise WebhookError("Missing order_id in session metadata")
    
    try:
        order_id = int(order_id_str)
    except ValueError:
        raise WebhookError(f"Invalid order_id: {order_id_str}")
    
    order = db.get(Order, order_id)
    if not order:
        raise WebhookError(f"Order {order_id} not found")
    
    # Only release if order is still reserved
    if order.status == OrderStatus.RESERVED:
        try:
            await inventory_client.release_stock(order_id)
        except Exception as e:
            logger.warning("Failed to release inventory on checkout expiry", order_id=order_id, error=str(e))
        
        order.status = OrderStatus.CANCELLED
        db.commit()
        
        logger.info("Order cancelled due to expired checkout", order_id=order_id)
        return {"status": "cancelled", "order_id": order_id}
    
    return {"status": "no_action", "order_id": order_id, "current_status": order.status}


# Event handlers registry
EVENT_HANDLERS = {
    "checkout.session.completed": handle_checkout_session_completed,
    "checkout.session.expired": handle_checkout_session_expired,
}


async def process_webhook(
    payload: bytes,
    signature: str,
    db: Session
) -> dict:
    """
    Main webhook processor.
    
    1. Verify signature
    2. Parse event
    3. Dispatch to handler
    """
    # Verify signature
    if not verify_stripe_signature(payload, signature, STRIPE_WEBHOOK_SECRET):
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Parse event
    event = parse_webhook_event(payload)
    event_type = event["type"]
    event_id = event["id"]
    
    logger.info("Webhook event received", event_type=event_type, event_id=event_id)
    
    # Get handler
    handler = EVENT_HANDLERS.get(event_type)
    if not handler:
        # Unknown event type - acknowledge but don't process
        logger.debug("Ignoring unknown event type", event_type=event_type)
        return {"status": "ignored", "event_type": event_type}
    
    # Process event
    result = await handler(event["data"], db)
    result["event_id"] = event_id
    
    return result

