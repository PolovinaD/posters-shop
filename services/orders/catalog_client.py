"""Client for communicating with the catalog service.

Exists for one reason: the price of an order line is not the client's to decide.
Before this module, `create_order` summed `unit_price` straight out of the
request body and that figure went on to Stripe, so a crafted request could buy a
poster for a cent. The catalog owns prices, so the catalog is asked.
"""
import os
from decimal import Decimal

import httpx

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401
from service_auth import internal_headers

CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog:8000")

TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# One breaker per destination service, as with inventory and payments.
catalog_cb = CircuitBreaker(
    service="catalog",
    failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class CatalogError(Exception):
    """Base exception for catalog service errors."""


class CatalogServiceError(CatalogError):
    """The catalog service could not be reached or failed to answer."""


class UnknownSkuError(CatalogError):
    """One or more SKUs are not sellable items in the catalog."""

    def __init__(self, skus: list[str]):
        self.skus = skus
        super().__init__(f"Unknown or inactive SKUs: {', '.join(skus)}")


async def resolve_prices(skus: list[str]) -> dict[str, dict]:
    """Return `{sku: {"name": str, "price": Decimal}}` for every SKU given.

    Raises UnknownSkuError if the catalog does not sell one of them, so an order
    can never be written for something that has no price.
    """
    if not skus:
        return {}

    async def _call():
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            response = await client.post(
                f"{CATALOG_SERVICE_URL}/internal/resolve-prices",
                json={"skus": skus},
            )
            response.raise_for_status()
            return response.json()

    try:
        data = await catalog_cb.call(_call)
    except CircuitOpenError:
        raise
    except httpx.HTTPError as e:
        raise CatalogServiceError(f"Catalog service unavailable: {e}") from e

    unknown = data.get("unknown", [])
    if unknown:
        raise UnknownSkuError(unknown)

    return {
        item["sku"]: {"name": item["name"], "price": Decimal(str(item["price"]))}
        for item in data.get("items", [])
    }
