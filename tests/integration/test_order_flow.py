"""
Integration test: full order flow via outbox pattern.
Requires all services running: make dev (or docker compose up -d)

Flow: log in → seed → create order → pay → poll until the order leaves PAID
The transition out of PAID is driven by the outbox worker (~2s poll interval)
delivering ORDER_PAID to the production service, so observing it confirms the
event-driven outbox path end-to-end.

Run with:
    pytest tests/integration/test_order_flow.py -v -s
"""
import time
import pytest
import httpx

POLL_INTERVAL = 0.25   # seconds between status checks
POLL_TIMEOUT = 30      # seconds before giving up

# States that prove the ORDER_PAID event was delivered by the outbox and acted on
# by the production service. PRODUCING itself is NOT a reliable assertion target:
# services/production/main.py:process_job calls notify_order_producing, then runs
# simulate_production_work (31 ms for a single item), then notify_order_shipped —
# so an order sits in PRODUCING for roughly a tenth of a second. Asserting on that
# instant makes the test a coin flip; asserting that the order moved past PAID
# along the production path is what the outbox actually guarantees.
POST_PRODUCTION_STATES = ("producing", "shipped", "delivered")

# The orders service takes the customer e-mail from the JWT `sub` claim and
# ignores the value in the body (services/orders/main.py:152-153), so the order
# is created against the logged-in owner regardless of what is sent here.
TEST_CUSTOMER_EMAIL = "integration-test@example.com"

# Unlike the e-mail (replaced from the JWT sub claim), the address is taken from
# the body as sent — it is required and validated, never overridden.
TEST_SHIPPING_ADDRESS = {
    "recipient_name": "Integration Test",
    "street": "Knez Mihailova 42",
    "city": "Beograd",
    "postal_code": "11000",
    "country": "Serbia",
    "phone": "+381601234567",
}


# ---------------------------------------------------------------------------
# Helper: poll order status until target reached or timeout
# ---------------------------------------------------------------------------

def wait_for_any_status(client: httpx.Client, orders_url: str, order_id: int,
                        targets: tuple[str, ...]) -> str | None:
    """
    Poll GET /orders/{order_id} every POLL_INTERVAL seconds.
    Returns the first status seen that is in `targets`, or None on timeout.
    """
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"{orders_url}/orders/{order_id}")
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status in targets:
                return status
        time.sleep(POLL_INTERVAL)
    return None


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_full_order_flow(http, catalog_url, inventory_url, orders_url, users_url,
                         logistics_url, anon_http):
    """
    Full order lifecycle: create → pay → past PAID via the outbox.

    Steps:
    0. Log in as the owner (the `http` fixture) so the guarded endpoints accept us
    1. Seed catalog and inventory (idempotent)
    2. Discover a SKU from the seeded catalog
    3. Create an order using catalog product data
    4. Pay the order (transitions RESERVED → PAID, emits ORDER_PAID to outbox)
    5. Poll until the order leaves "paid" (outbox delivers order_paid to production)
    6. Assert a post-production state was reached within 30s
    7. Assert the shipment carries its own copy of the delivery address
    8. Assert an UNAUTHENTICATED caller cannot read shipments at all

    Authentication: the `http` fixture logs in as the bootstrap owner
    (services/users/init_db.py) and carries the bearer token on every request.
    An owner token is required throughout — /seed on catalog and inventory and
    POST /orders/{id}/pay are guarded by require_owner, and POST /orders needs
    an authenticated caller (Depends(get_current_user_claims)).
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
        "shipping_address": TEST_SHIPPING_ADDRESS,
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

    assert order.get("shipping_address") == TEST_SHIPPING_ADDRESS, (
        f"Order did not echo the shipping address back: {order.get('shipping_address')}"
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

    # Step 5: Poll until the order has moved past PAID along the production path.
    # The outbox worker polls every 2s and POSTs ORDER_PAID to the production
    # service, whose job worker then drives producing -> shipped.
    observed = wait_for_any_status(http, orders_url, order_id, POST_PRODUCTION_STATES)
    assert observed, (
        f"Order {order_id} never left 'paid' within {POLL_TIMEOUT}s. "
        "Check that the outbox worker is running and the production service is up."
    )

    # Step 6: Final assertion — the order is in a post-production state, which is
    # only reachable if the ORDER_PAID event was delivered and consumed.
    final = http.get(f"{orders_url}/orders/{order_id}")
    assert final.status_code == 200, f"Could not get final order state: {final.text}"
    assert final.json()["status"] in POST_PRODUCTION_STATES, (
        f"Expected one of {POST_PRODUCTION_STATES} but got: {final.json()['status']}"
    )
    print(f"\n  outbox path confirmed: order {order_id} reached '{observed}'")

    # Step 7: the delivery copy. production calls POST /ship on its way to
    # 'shipped', so once the order is shipped the shipment row exists and must
    # already carry its own copy of the address — read from logistics_schema
    # alone, with orders not involved.
    shipped = wait_for_any_status(http, orders_url, order_id, ("shipped", "delivered"))
    assert shipped, f"Order {order_id} never reached 'shipped' within {POLL_TIMEOUT}s"

    shipment_resp = http.get(f"{logistics_url}/shipments/order/{order_id}")
    assert shipment_resp.status_code == 200, (
        f"No shipment for order {order_id}: {shipment_resp.status_code} {shipment_resp.text}"
    )
    assert shipment_resp.json()["shipping_address"] == TEST_SHIPPING_ADDRESS, (
        "Shipment is missing the delivery copy of the address: "
        f"{shipment_resp.json().get('shipping_address')}"
    )
    print(f"  delivery copy confirmed: shipment for order {order_id} carries the address")

    # Step 8: regression lock for the 260912-rnl customer-PII disclosure.
    # These three GET routes carried no authorization at all (pre-existing --
    # `git show 23f6972:services/logistics/main.py` shows only Depends(get_db)).
    # That was latent until 260912-n7c enriched the payload with shipping_address,
    # at which point `curl :3000/api/logistics/shipments` returned every customer's
    # name, street, city, postal code and phone in ONE unauthenticated request.
    # `anon_http` is defined in tests/conftest.py and has shipped unused until now;
    # this is its first consumer.
    anon = anon_http.get(f"{logistics_url}/shipments")
    assert anon.status_code == 401, (
        "GET /shipments must reject an unauthenticated caller, got "
        f"{anon.status_code}: {anon.text[:200]}"
    )
    anon_one = anon_http.get(f"{logistics_url}/shipments/order/{order_id}")
    assert anon_one.status_code == 401, (
        "GET /shipments/order/{id} must reject an unauthenticated caller, got "
        f"{anon_one.status_code}: {anon_one.text[:200]}"
    )
    # The status code alone could pass while a body still leaked. This asserts the
    # property that actually matters: no customer PII survives in the response.
    assert TEST_SHIPPING_ADDRESS["recipient_name"] not in anon.text, (
        "Customer PII leaked to an unauthenticated caller"
    )
    print("  shipment reads are closed to anonymous callers")
