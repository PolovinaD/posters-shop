"""Escrow reconciler: closes the gaps a browser (or an outage) can leave open.

(a) the customer paid on chain but the tab died before POST /escrow/verify
    -> mark the order paid (the SAME mark_order_paid the Stripe webhook runs);
(b) logistics reported a courier while payments was down, or before the
    contract was funded -> retry the on-chain binding;
(c) an order was cancelled / expired while its refund failed -> retry cancel().

Same shape as status_metrics.orders_by_status_worker: work-then-sleep, one
instance per replica, errors logged and swallowed. Two replicas may race on the
same order; every action is idempotent (mark_order_paid returns False when
already PAID; assignCourier reverts 'Transfer not complete.' / 'Order closed.',
which is caught and logged).
"""
import asyncio
import os

from sqlalchemy import select

from database import SessionLocal
from models import Order, OrderStatus, EscrowStatus, PaymentMethod
from escrow_rules import decide_reconcile_action
from order_paid import mark_order_paid, InvalidPaidTransition
import payment_client
from payment_client import PaymentServiceError, EscrowContractMissingError, EscrowRejectedError
from circuit_breaker import CircuitOpenError
from logger import get_logger

logger = get_logger("escrow_reconciler")

RECONCILE_INTERVAL_SECONDS = float(os.getenv("ESCROW_RECONCILE_INTERVAL", "15"))
ACTIONS = ("mark_paid", "bind_courier", "sync_in_delivery", "refund", "mark_failed", "noop")


def open_escrow_orders_query():
    """Escrow orders with a deployed contract whose escrow_status is still open."""
    return select(Order).where(
        Order.payment_method == PaymentMethod.ESCROW,
        Order.escrow_contract_address.is_not(None),
        Order.escrow_status.in_(EscrowStatus.OPEN),
    )


async def reconcile_once(db) -> dict:
    """One pass over the open escrow orders. Returns a count per action."""
    counts = {a: 0 for a in ACTIONS}
    orders = db.execute(open_escrow_orders_query()).scalars().all()

    for order in orders:
        try:
            chain = await payment_client.get_escrow_state(order.escrow_contract_address)
            chain_state = chain["state"]
        except EscrowContractMissingError:
            chain_state = None
        except (CircuitOpenError, PaymentServiceError) as e:
            logger.warning(
                "Escrow reconcile skipped: payments unavailable",
                order_id=order.id, error=str(e),
            )
            counts["noop"] += 1
            continue

        action = decide_reconcile_action(
            order.status, order.escrow_status, order.courier_wallet, chain_state
        )
        counts[action] += 1

        if action == "mark_paid":
            # Set escrow_status BEFORE mark_order_paid so its single commit covers both.
            order.escrow_status = EscrowStatus.FUNDED if chain_state == "funded" else chain_state
            try:
                await mark_order_paid(db, order, payment_ref=order.escrow_contract_address)
            except InvalidPaidTransition as e:
                logger.warning("Reconciler could not mark order paid", order_id=order.id, error=str(e))
                db.rollback()
                continue
            logger.info("Reconciler marked escrow order paid", order_id=order.id, chain_state=chain_state)

        elif action == "bind_courier":
            try:
                await payment_client.assign_escrow_courier(
                    order.escrow_contract_address, order.courier_wallet
                )
                order.escrow_status = EscrowStatus.IN_DELIVERY
                db.commit()
                logger.info(
                    "Reconciler bound courier on chain",
                    order_id=order.id, courier_wallet=order.courier_wallet,
                )
            except EscrowRejectedError as e:
                logger.warning("Courier binding rejected", order_id=order.id, reason=e.reason)
            except (CircuitOpenError, PaymentServiceError) as e:
                logger.warning("Courier binding deferred", order_id=order.id, error=str(e))

        elif action == "sync_in_delivery":
            order.escrow_status = EscrowStatus.IN_DELIVERY
            db.commit()
            logger.info("Reconciler synced escrow_status from chain", order_id=order.id, escrow_status=EscrowStatus.IN_DELIVERY)

        elif action == "refund":
            # Cancelled/failed order with an open contract: cancel() returns the
            # balance to the customer.
            try:
                await payment_client.cancel_escrow(order.escrow_contract_address)
                order.escrow_status = EscrowStatus.CANCELLED
                db.commit()
                logger.info("Reconciler refunded escrow for closed order", order_id=order.id)
            except EscrowRejectedError as e:
                logger.warning("Escrow refund rejected", order_id=order.id, reason=e.reason)
            except (CircuitOpenError, PaymentServiceError) as e:
                logger.warning("Escrow refund deferred", order_id=order.id, error=str(e))

        elif action == "mark_failed":
            order.escrow_status = EscrowStatus.FAILED
            db.commit()
            logger.error(
                "Escrow contract vanished (chain reset?)",
                order_id=order.id, contract_address=order.escrow_contract_address,
            )

    return counts


async def escrow_reconciler_worker(interval: float = RECONCILE_INTERVAL_SECONDS):
    """Run reconcile_once every `interval` seconds until cancelled."""
    logger.info("Escrow reconciler started", interval=interval)

    while True:
        try:
            with SessionLocal() as db:
                counts = await reconcile_once(db)
                if any(counts[a] for a in ACTIONS if a != "noop"):
                    logger.info("Escrow reconcile actions", **counts)
        except Exception as e:
            logger.error("Escrow reconcile failed", error=str(e), exc_info=True)

        await asyncio.sleep(interval)
