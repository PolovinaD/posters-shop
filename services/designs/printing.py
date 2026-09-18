"""Print-this (D-06/D-11/D-12): turn a ready design into an unlisted catalog family
plus virtual stock, so it rides the existing cart -> order -> pay -> production
pipeline unchanged.

Pure helpers (SKU scheme, name, payload builders) and one orchestrator. Nothing here
imports main, the clients or the session factory: the route passes them in, so the
unit tests drive `print_generation` with fake clients and a MagicMock session.

SKU scheme (recognisable from an ORDER_PAID item SKU alone, D-07):
    motif    AI-{generation_id}          the catalog family — never sellable itself
    variant  AI-{generation_id}-{size}   A4 | A3 | A2 | A1 — what the cart holds
"""
import re
from decimal import Decimal

SIZES = ["A4", "A3", "A2", "A1"]
# == the catalog seed ladder (services/catalog/main.py seed_catalog): -5 / 0 / +10 / +25 from the base price
SIZE_UPLIFT = {"A4": Decimal("-5.00"), "A3": Decimal("0.00"), "A2": Decimal("10.00"), "A1": Decimal("25.00")}
SKU_PREFIX = "AI-"
VARIANT_SKU_RE = re.compile(r"^AI-(\d+)-(A4|A3|A2|A1)$")
CATEGORY = "Custom"
NAME_PREFIX = "Custom: "
NAME_PROMPT_CHARS = 60
_CENTS = Decimal("0.01")


def motif_sku(generation_id: int) -> str:
    return f"{SKU_PREFIX}{generation_id}"


def variant_sku(generation_id: int, size: str) -> str:
    return f"{motif_sku(generation_id)}-{size}"


def generation_id_from_sku(sku: str | None) -> int | None:
    """The generation behind a sellable variant SKU, or None for anything else (the
    motif itself, an ordinary poster, a frame, an unknown format)."""
    m = VARIANT_SKU_RE.match(sku or "")
    return int(m.group(1)) if m else None


def product_name(prompt: str) -> str:
    """'Custom: ' + the whitespace-collapsed prompt capped at NAME_PROMPT_CHARS."""
    return NAME_PREFIX + " ".join((prompt or "").split())[:NAME_PROMPT_CHARS]


def build_product_payload(gen, image_url: str, base_price: Decimal) -> dict:
    """The catalog POST /internal/products body: unlisted family, four ladder-priced variants."""
    return {
        "sku": motif_sku(gen.id),
        "name": product_name(gen.prompt),
        "description": (gen.prompt or "").strip(),
        "category": CATEGORY,
        "image_url": image_url,
        "listed": False,
        "active": True,
        "variants": [
            {"size": size, "price": f"{(base_price + SIZE_UPLIFT[size]).quantize(_CENTS)}"}
            for size in SIZES
        ],
    }


def build_stock_items(gen, name: str, stock: int) -> list[dict]:
    """The inventory POST /internal/stock items: one virtual-stock row per variant."""
    return [{"sku": variant_sku(gen.id, size), "name": f"{name} ({size})", "available": stock} for size in SIZES]


async def print_generation(db, gen, *, catalog, inventory, image_url: str, base_price: Decimal, stock: int) -> tuple[str, bool]:
    """Returns (sku, created).

    Order: catalog first (idempotent), then inventory (idempotent), then the row — so a
    failure anywhere leaves catalog_product_sku NULL and the customer's retry completes
    the missing half (catalog answers 200 for the family that already exists, inventory
    skips the rows that already exist). Exceptions from the clients propagate; the route
    maps them to 502/503.
    """
    if gen.catalog_product_sku:
        return gen.catalog_product_sku, False
    payload = build_product_payload(gen, image_url, base_price)
    await catalog.create_product_family(payload)
    await inventory.create_stock(build_stock_items(gen, payload["name"], stock))
    gen.catalog_product_sku = payload["sku"]
    db.commit()
    return payload["sku"], True
