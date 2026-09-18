"""Typed client for the catalog write path used by Print-this (D-06).

One breaker per destination, a service token per call (the orders/catalog_client.py
shape). A 4xx from catalog is a business answer (`CatalogRejectedError`, whitelisted
in circuit_breaker._BUSINESS_ERROR_NAMES) and never trips the breaker; 5xx and
network errors (`CatalogServiceError`) do.
"""
import os

import httpx

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401
from service_auth import internal_headers

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog:8000")

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

catalog_cb = CircuitBreaker(
    service="catalog",
    failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class CatalogServiceError(Exception):
    """5xx / network — the catalog could not be reached or failed; trips the breaker."""


class CatalogRejectedError(Exception):
    """4xx — the catalog refused the payload (unknown format, bad sku); never trips the breaker."""


async def create_product_family(payload: dict) -> dict:
    """POST /internal/products: an unlisted family with its variants in one transaction.

    Idempotent on the catalog side (an existing sku answers 200 with the family as it
    is), so a retry after a partial print is safe.
    """
    async def _call():
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            response = await client.post(f"{CATALOG_SERVICE_URL}/internal/products", json=payload)
            if 400 <= response.status_code < 500:
                raise CatalogRejectedError(f"catalog {response.status_code}: {response.text[:200]}")
            response.raise_for_status()
            return response.json()

    try:
        return await catalog_cb.call(_call)
    except (CircuitOpenError, CatalogRejectedError):
        raise
    except httpx.HTTPError as e:
        raise CatalogServiceError(f"Catalog service unavailable: {e}") from e
