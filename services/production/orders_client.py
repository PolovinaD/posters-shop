"""Client for communicating with the orders service."""
import os
import httpx

ORDERS_SERVICE_URL = os.getenv("ORDERS_SERVICE_URL", "http://orders:8000")
LOGISTICS_SERVICE_URL = os.getenv("LOGISTICS_SERVICE_URL", "http://logistics:8000")

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class ServiceError(Exception):
    """Base exception for service communication errors."""
    pass


async def notify_order_producing(order_id: int) -> dict:
    """Notify orders service that production has started."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            response = await client.post(f"{ORDERS_SERVICE_URL}/orders/{order_id}/produce")
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[production] Failed to notify order {order_id} producing: {response.status_code}")
                return {"error": response.text}
        except httpx.RequestError as e:
            print(f"[production] Failed to connect to orders service: {e}")
            return {"error": str(e)}


async def notify_order_shipped(order_id: int) -> dict:
    """Notify orders service that production is complete and trigger shipping."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            # First, create shipment in logistics
            ship_response = await client.post(
                f"{LOGISTICS_SERVICE_URL}/ship",
                json=order_id  # logistics expects just the order_id
            )
            
            if ship_response.status_code == 200:
                shipment = ship_response.json()
                print(f"[production] Created shipment for order {order_id}: {shipment}")
            else:
                print(f"[production] Failed to create shipment: {ship_response.status_code}")
            
            # Then, update order status to shipped
            response = await client.post(f"{ORDERS_SERVICE_URL}/orders/{order_id}/ship")
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[production] Failed to notify order {order_id} shipped: {response.status_code}")
                return {"error": response.text}
                
        except httpx.RequestError as e:
            print(f"[production] Failed to connect to services: {e}")
            return {"error": str(e)}

