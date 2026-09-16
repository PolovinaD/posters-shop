"""The one place an order becomes PAID from a verified payment.

Used by the Stripe webhook (checkout.session.completed), by escrow verify and
by the escrow reconciler. NOT used by the owner-only POST /orders/{id}/pay,
whose inventory failure semantics differ (it refuses; here the payment has
already happened, so inventory failure is logged and the order is still
honoured).
"""
from sqlalchemy.orm import Session

from models import Order, OrderStatus
from outbox import emit_event
import inventory_client
from logger import get_logger

logger = get_logger("order_paid")


class InvalidPaidTransition(Exception):
    """The order's current status does not allow a transition to PAID."""


async def mark_order_paid(db: Session, order: Order, payment_ref: str | None = None) -> bool:
    """Commit stock, set PAID and emit ORDER_PAID in ONE transaction.

    Returns False when the order is already PAID (idempotent), True when it was
    marked now. Raises InvalidPaidTransition for any other non-payable status.
    """
    if order.status == OrderStatus.PAID:
        logger.info("Order already paid (idempotent)", order_id=order.id)
        return False

    if not OrderStatus.can_transition(order.status, OrderStatus.PAID):
        raise InvalidPaidTransition(
            f"Cannot transition order {order.id} from {order.status} to paid"
        )

    try:
        await inventory_client.commit_stock(order.id)
    except Exception as e:
        # The payment already happened: honour it, and let operators see the gap.
        logger.warning("Failed to commit inventory, continuing with payment", order_id=order.id, error=str(e))

    order.status = OrderStatus.PAID
    if payment_ref:
        order.payment_intent_id = payment_ref

    items = [
        {"sku": item.sku, "name": item.name, "quantity": item.quantity}
        for item in order.items
    ]
    emit_event(
        db=db,
        event_type="ORDER_PAID",
        aggregate_type="order",
        aggregate_id=str(order.id),
        payload={
            "order_id": order.id,
            "customer_email": order.customer_email,
            "total_amount": str(order.total_amount),
            "payment_intent": payment_ref,
            "items": items,
        },
    )

    db.commit()

    logger.info("Order marked as paid", order_id=order.id, payment_ref=payment_ref)
    return True
