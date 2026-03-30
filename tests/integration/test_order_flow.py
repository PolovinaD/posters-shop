"""
Integration test: full order flow via outbox pattern.
Requires all services running: make dev (or docker compose up -d)

Flow: seed → create order → pay → poll until PRODUCING
The PRODUCING transition is delivered by the outbox worker (~2s poll interval).
This test confirms the event-driven outbox path end-to-end.

Run with:
    pytest tests/integration/test_order_flow.py -v -s
"""
import time
import pytest
import httpx

POLL_INTERVAL = 2   # seconds between status checks
POLL_TIMEOUT = 30   # seconds before giving up

TEST_CUSTOMER_EMAIL = "integration-test@example.com"


# ---------------------------------------------------------------------------
# Helper: poll order status until target reached or timeout
# ---------------------------------------------------------------------------

def wait_for_status(client: httpx.Client, orders_url: str, order_id: int, target: str) -> bool:
    """
    Poll GET /orders/{order_id} every POLL_INTERVAL seconds.
    Returns True when status == target, False on timeout.
    """
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"{orders_url}/orders/{order_id}")
        if resp.status_code == 200 and resp.json().get("status") == target:
            return True
        time.sleep(POLL_INTERVAL)
    return False


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_full_order_flow(http, catalog_url, inventory_url, orders_url, users_url):
    """
    Full order lifecycle: create → pay → PRODUCING via outbox.

    Steps:
    1. Seed catalog and inventory (idempotent)
    2. Discover a SKU from the seeded catalog
    3. Create an order using catalog product data
    4. Pay the order (transitions RESERVED → PAID, emits ORDER_PAID to outbox)
    5. Poll until status == "producing" (outbox delivers order_paid event to production)
    6. Assert PRODUCING state reached within 30s

    No auth required: POST /orders and POST /orders/{id}/pay use only Depends(get_db).
    """
    # Step 1: Seed (idempotent — safe to call multiple times)
    seed_catalog = http.post(f"{catalog_url}/seed")
    assert seed_catalog.status_code in (200, 201), (
        f"Catalog seed failed: {seed_catalog.status_code} {seed_catalog.text}"
    )

    seed_inv = http.post(f"{inventory_url}/seed")
    assert seed_inv.status_code in (200, 201), (
        f"Inventory seed failed: {seed_inv.status_code} {seed_inv.text}"
    )

    # Step 2: Discover a SKU from the seeded catalog
    # GET /products returns list[ProductOut]: {id, sku, name, price, category, ...}
    products_resp = http.get(f"{catalog_url}/products")
    assert products_resp.status_code == 200, f"Could not list products: {products_resp.text}"
    products = products_resp.json()
    assert len(products) > 0, "Catalog seed produced no products"

    # Use the first product — fields: sku, name, price (Decimal as string)
    product = products[0]
    sku = product["sku"]
    name = product["name"]
    unit_price = float(product["price"])
    assert sku, f"No SKU in product: {product}"
    assert name, f"No name in product: {product}"
    assert unit_price > 0, f"No valid price in product: {product}"

    # Step 3: Create an order
    # OrderCreate schema: {customer_email, items: [{sku, name, quantity, unit_price}]}
    order_payload = {
        "customer_email": TEST_CUSTOMER_EMAIL,
        "items": [{"sku": sku, "name": name, "quantity": 1, "unit_price": unit_price}],
    }
    create_resp = http.post(f"{orders_url}/orders", json=order_payload)
    assert create_resp.status_code in (200, 201), (
        f"Order creation failed: {create_resp.status_code} {create_resp.text}"
    )
    order = create_resp.json()
    order_id = order.get("id")
    assert order_id, f"No order ID in response: {order}"

    # After creation the order should be in RESERVED status
    # (inventory reservation happens synchronously during create_order)
    assert order.get("status") == "reserved", (
        f"Expected 'reserved' after creation but got: {order.get('status')}"
    )

    # Step 4: Pay the order
    # POST /orders/{order_id}/pay — transitions RESERVED → PAID and emits ORDER_PAID to outbox
    pay_resp = http.post(f"{orders_url}/orders/{order_id}/pay")
    assert pay_resp.status_code in (200, 201), (
        f"Pay failed: {pay_resp.status_code} {pay_resp.text}"
    )
    paid_order = pay_resp.json()
    assert paid_order.get("status") == "paid", (
        f"Expected 'paid' after payment but got: {paid_order.get('status')}"
    )

    # Step 5: Poll until PRODUCING (outbox worker delivers order_paid event)
    # The outbox worker polls every 2s; production service handles ORDER_PAID event
    # and transitions order to PRODUCING via POST /orders/{id}/produce
    reached = wait_for_status(http, orders_url, order_id, "producing")
    assert reached, (
        f"Order {order_id} did not reach 'producing' within {POLL_TIMEOUT}s. "
        "Check that the outbox worker is running and the production service is up."
    )

    # Step 6: Final assertion — confirm the order is in PRODUCING state
    final = http.get(f"{orders_url}/orders/{order_id}")
    assert final.status_code == 200, f"Could not get final order state: {final.text}"
    assert final.json()["status"] == "producing", (
        f"Expected producing but got: {final.json()['status']}"
    )
