"""
Stripe Webhook Handler

Handles incoming webhooks from Stripe.

Key concepts:
1. SIGNATURE VERIFICATION - All webhooks verified using stripe.Webhook.construct_event()
   per D-SHOP-01: "Replace custom webhook signature validation with stripe.Webhook.construct_event()"
2. IDEMPOTENCY - Events may be sent multiple times; handlers check order.status == PAID
3. QUICK RESPONSE - Respond 200 quickly, do processing in-place
"""
import os
from typing import Optional

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import Order, OrderStatus
from outbox import emit_event
import inventory_client
from logger import get_logger

logger = get_logger("webhook")

# Webhook secret — must match the Stripe Dashboard webhook signing secret
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret_key_12345")

# stripe.Webhook.construct_event() requires an API key to be set even for signature-only verification
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# Kept for documentation; stripe SDK handles timestamp tolerance internally (default: 300s)
TIMESTAMP_TOLERANCE = 300


class WebhookError(Exception):
    """Raised when webhook processing fails."""
    pass


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

    Uses stripe.Webhook.construct_event() for signature verification (per D-SHOP-01).
    This replaces the manual HMAC implementation — the stripe SDK handles:
    1. Signature verification
    2. Timestamp tolerance (replay attack prevention)
    3. JSON parsing and field validation
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError as e:
        logger.warning("Stripe webhook signature verification failed", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid signature")
    except ValueError as e:
        logger.warning("Stripe webhook payload invalid", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid payload")

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
