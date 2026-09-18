"""Typed client for the inventory write path used by Print-this (D-11, "virtual stock").

Same shape as catalog_client.py: one breaker for the destination, a service token per
call, 4xx -> `InventoryRejectedError` (business, never trips the breaker), 5xx/network
-> `InventoryServiceError` (trips it).
"""
import os

import httpx

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401
from service_auth import internal_headers

INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8000")

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

inventory_cb = CircuitBreaker(
    service="inventory",
    failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class InventoryServiceError(Exception):
    """5xx / network — inventory could not be reached or failed; trips the breaker."""


class InventoryRejectedError(Exception):
    """4xx — inventory refused the payload; never trips the breaker."""


async def create_stock(items: list[dict]) -> dict:
    """POST /internal/stock: stock rows for the SKUs that do not exist yet.

    Idempotent on the inventory side (existing SKUs are skipped, not 400'd), so a
    retry after a partial print is safe. Returns {"created": [...], "skipped": [...]}.
    """
    async def _call():
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            response = await client.post(f"{INVENTORY_SERVICE_URL}/internal/stock", json={"items": items})
            if 400 <= response.status_code < 500:
                raise InventoryRejectedError(f"inventory {response.status_code}: {response.text[:200]}")
            response.raise_for_status()
            return response.json()

    try:
        return await inventory_cb.call(_call)
    except (CircuitOpenError, InventoryRejectedError):
        raise
    except httpx.HTTPError as e:
        raise InventoryServiceError(f"Inventory service unavailable: {e}") from e
