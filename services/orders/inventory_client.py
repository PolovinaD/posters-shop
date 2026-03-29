"""Client for communicating with the inventory service."""
import os
import httpx
from typing import Optional

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8000")

# Timeout settings
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Circuit breaker singleton — one per destination service (D-02)
# Thresholds read from env vars at startup (D-04)
inventory_cb = CircuitBreaker(
    service="inventory",
    failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class InventoryError(Exception):
    """Base exception for inventory service errors."""
    pass


class InsufficientStockError(InventoryError):
    """Raised when there's not enough stock to reserve."""
    def __init__(self, sku: str, available: int, requested: int):
        self.sku = sku
        self.available = available
        self.requested = requested
        super().__init__(f"Insufficient stock for {sku}: available={available}, requested={requested}")


class SkuNotFoundError(InventoryError):
    """Raised when SKU doesn't exist in inventory."""
    def __init__(self, sku: str):
        self.sku = sku
        super().__init__(f"SKU not found: {sku}")


class InventoryServiceError(InventoryError):
    """Raised when inventory service is unavailable or returns unexpected error."""
    pass


async def reserve_stock(order_id: int, sku: str, quantity: int, ttl_minutes: int = 15) -> dict:
    """
    Reserve stock for an order.

    Returns reservation details on success.
    Raises InsufficientStockError, SkuNotFoundError, or InventoryServiceError on failure.
    Raises CircuitOpenError when inventory circuit is open.
    """
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/reserve",
                    json={
                        "order_id": order_id,
                        "sku": sku,
                        "quantity": quantity,
                        "ttl_minutes": ttl_minutes
                    }
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 409:
                    # Insufficient stock
                    raise InsufficientStockError(sku, 0, quantity)
                elif response.status_code == 404:
                    raise SkuNotFoundError(sku)
                else:
                    raise InventoryServiceError(f"Unexpected response: {response.status_code}")

            except httpx.RequestError as e:
                raise InventoryServiceError(f"Failed to connect to inventory service: {e}")

    return await inventory_cb.call(_call)


async def release_stock(order_id: int, sku: Optional[str] = None) -> dict:
    """
    Release reserved stock for an order (on cancellation or failure).

    If sku is None, releases all reservations for the order.
    Raises CircuitOpenError when inventory circuit is open.
    """
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                payload = {"order_id": order_id}
                if sku:
                    payload["sku"] = sku

                response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/release",
                    json=payload
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    # No reservations found - that's ok for idempotency
                    return {"released_count": 0, "released_quantity": 0}
                else:
                    raise InventoryServiceError(f"Unexpected response: {response.status_code}")

            except httpx.RequestError as e:
                raise InventoryServiceError(f"Failed to connect to inventory service: {e}")

    return await inventory_cb.call(_call)


async def commit_stock(order_id: int, sku: Optional[str] = None) -> dict:
    """
    Commit reserved stock after successful payment.
    Stock is permanently deducted.
    Raises CircuitOpenError when inventory circuit is open.
    """
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                payload = {"order_id": order_id}
                if sku:
                    payload["sku"] = sku

                response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/commit",
                    json=payload
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    raise InventoryServiceError(f"No reservations found to commit for order {order_id}")
                else:
                    raise InventoryServiceError(f"Unexpected response: {response.status_code}")

            except httpx.RequestError as e:
                raise InventoryServiceError(f"Failed to connect to inventory service: {e}")

    return await inventory_cb.call(_call)


async def check_stock(skus: list[str]) -> dict:
    """
    Check stock availability for multiple SKUs.
    Raises CircuitOpenError when inventory circuit is open.
    """
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/stock/check",
                    json={"skus": skus}
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    raise InventoryServiceError(f"Unexpected response: {response.status_code}")

            except httpx.RequestError as e:
                raise InventoryServiceError(f"Failed to connect to inventory service: {e}")

    return await inventory_cb.call(_call)
