import os
import httpx
import logging

from service_auth import internal_headers

logger = logging.getLogger(__name__)

ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://orders:8000")


async def notify_order_delivered(order_id: int) -> bool:
    """
    Notify the orders service that an order has been delivered.
    Returns True if successful, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=internal_headers()) as client:
            response = await client.post(
                f"{ORDERS_SERVICE_URL}/orders/{order_id}/deliver"
            )
            if response.status_code == 200:
                logger.info(f"Order {order_id} marked as delivered")
                return True
            else:
                logger.error(
                    f"Failed to mark order {order_id} as delivered: "
                    f"{response.status_code} - {response.text}"
                )
                return False
    except Exception as e:
        logger.error(f"Error notifying orders service for order {order_id}: {e}")
        return False


async def notify_order_shipped(order_id: int) -> bool:
    """
    Notify the orders service that an order has been shipped (dispatched).
    Returns True if successful, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=internal_headers()) as client:
            response = await client.post(
                f"{ORDERS_SERVICE_URL}/orders/{order_id}/ship"
            )
            if response.status_code == 200:
                logger.info(f"Order {order_id} marked as shipped")
                return True
            else:
                logger.error(
                    f"Failed to mark order {order_id} as shipped: "
                    f"{response.status_code} - {response.text}"
                )
                return False
    except Exception as e:
        logger.error(f"Error notifying orders service for order {order_id}: {e}")
        return False


async def fetch_shipping_address(order_id: int) -> dict | None:
    """Fetch an order's shipping address, once, at shipment creation.

    Returns the address dict, or None when orders cannot supply one. The caller
    still creates the shipment — a missing address must not block dispatch.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=internal_headers()) as client:
            response = await client.get(
                f"{ORDERS_SERVICE_URL}/internal/orders/{order_id}/shipping-address"
            )
            if response.status_code == 200:
                return response.json().get("shipping_address")
            logger.warning(
                f"Could not fetch shipping address for order {order_id}: "
                f"{response.status_code} - {response.text}"
            )
            return None
    except Exception as e:
        logger.error(f"Error fetching shipping address for order {order_id}: {e}")
        return None


async def notify_courier_assigned(order_id: int, courier_wallet: str) -> bool:
    """Tell orders which wallet picked the parcel up (CONTRACT B: POST /internal/orders/{id}/courier).

    Orders binds it to the escrow contract when the order is an escrow order; for
    card orders it only stores it. Fire-and-forget: any non-200 (incl. 404 before
    the orders side ships) is logged and swallowed.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=internal_headers()) as client:
            response = await client.post(
                f"{ORDERS_SERVICE_URL}/internal/orders/{order_id}/courier",
                json={"courier_wallet": courier_wallet},
            )
            if response.status_code == 200:
                logger.info(f"Courier wallet sent to orders for order {order_id}: {response.text}")
                return True
            logger.error(
                f"Failed to send courier wallet for order {order_id}: "
                f"{response.status_code} - {response.text}"
            )
            return False
    except Exception as e:
        logger.error(f"Error sending courier wallet for order {order_id}: {e}")
        return False
