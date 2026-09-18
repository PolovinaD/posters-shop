"""
Integration test: the AI poster studio end to end on the fake provider.

Requires the whole compose stack (make dev / docker compose up -d) INCLUDING the
`designs` service on 8010 with `IMAGE_PROVIDER=fake` (the compose default). Like
test_escrow_flow.py this file skips nothing: a stack without the studio is a
broken demo stack, and a real provider would cost money on every run — the
`[reject]` hook that drives the refusal path only exists on the fake provider.

Flow (the studio page, without a browser):
  POST /generations 202 -> the worker claims the row and the fake provider paints
  a PNG -> GET /images/{key} serves it -> POST /generations/{id}/print creates the
  unlisted catalog family AI-{id} (A4..A1 on the seed ladder) plus virtual stock
  -> an ordinary order for AI-{id}-A3 through the UNCHANGED orders service ->
  owner /pay -> the outbox fans ORDER_PAID out to production, notifications and
  designs -> the generation gets `purchased_at` -> the style profile refresh
  counts the purchase -> a `[reject]` prompt ends `failed` with the reason.

Idempotent across runs: every run makes fresh generations, the owner account is
quota-exempt (D-14) and the seeds are no-ops without `force`.

Run with:
    pytest tests/integration/test_design_flow.py -v -s
"""
import re
import time
from decimal import Decimal

import httpx

from tests.integration.test_order_flow import (
    POLL_INTERVAL,
    POLL_TIMEOUT,
    POST_PRODUCTION_STATES,
    TEST_CUSTOMER_EMAIL,
    TEST_SHIPPING_ADDRESS,
    wait_for_any_status,
)

# printing.py: AI-{id} motif, AI-{id}-{size} variants, seed ladder -5 / 0 / +10 / +25
# from AI_POSTER_BASE_PRICE (29.99 in compose).
SIZES = ("A4", "A3", "A2", "A1")
LADDER = {"A4": Decimal("24.99"), "A3": Decimal("29.99"), "A2": Decimal("39.99"), "A1": Decimal("54.99")}
ORDERED_SIZE = "A3"

# storage.KEY_RE (32 hex + .png) behind the compose DESIGNS_PUBLIC_URL_PREFIX.
IMAGE_URL_RE = re.compile(r"^/api/designs/images/[0-9a-f]{32}\.png$")

TERMINAL_STATES = ("ready", "failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def wait_for_generation(client: httpx.Client, designs_url: str, gen_id: int,
                        targets: tuple[str, ...] = TERMINAL_STATES) -> dict:
    """
    Poll GET /generations/{gen_id} every POLL_INTERVAL seconds until `status` is in
    `targets` (or POLL_TIMEOUT elapses). Returns the last JSON seen either way, so a
    failing assertion shows the row the worker left behind.
    """
    deadline = time.monotonic() + POLL_TIMEOUT
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"{designs_url}/generations/{gen_id}")
        if resp.status_code == 200:
            last = resp.json()
            if last.get("status") in targets:
                return last
        time.sleep(POLL_INTERVAL)
    return last


def wait_for_purchase(client: httpx.Client, designs_url: str, gen_id: int) -> dict:
    """Poll GET /generations/{gen_id} until `purchased_at` is set (the outbox has
    delivered ORDER_PAID to designs) or POLL_TIMEOUT elapses."""
    deadline = time.monotonic() + POLL_TIMEOUT
    last: dict = {}
    while time.monotonic() < deadline:
        resp = client.get(f"{designs_url}/generations/{gen_id}")
        if resp.status_code == 200:
            last = resp.json()
            if last.get("purchased_at"):
                return last
        time.sleep(POLL_INTERVAL)
    return last


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def test_generate_print_order_paid_purchased(http, designs_url, catalog_url,
                                             inventory_url, orders_url):
    """
    generate -> ready -> image served -> print -> unlisted family -> order ->
    pay -> production consumed it -> designs consumed it (purchased_at) ->
    style profile counts the purchase -> a refused prompt fails with a reason.
    """
    # Step 1: seed (idempotent WITHOUT force — force=true would wipe the AI-* families)
    for url in (f"{catalog_url}/seed", f"{inventory_url}/seed"):
        seed = http.post(url)
        assert seed.status_code in (200, 201), f"Seed failed: {url} {seed.status_code} {seed.text}"

    # Step 2: queue a generation — 202 + a queued row
    create = http.post(
        f"{designs_url}/generations",
        json={"prompt": "integration test poster: geometric lighthouse at dusk"},
    )
    assert create.status_code == 202, f"POST /generations: {create.status_code} {create.text}"
    queued = create.json()
    gen_id = queued["id"]
    assert queued["status"] == "queued", queued
    assert queued["image_url"] is None, queued

    # Step 3: the worker + fake provider make it ready; the PNG is served publicly
    gen = wait_for_generation(http, designs_url, gen_id)
    assert gen.get("status") == "ready", (
        f"Generation {gen_id} did not become ready within {POLL_TIMEOUT}s: {gen}"
    )
    image_url = gen["image_url"]
    assert image_url and IMAGE_URL_RE.match(image_url), f"Unexpected image_url: {image_url!r}"
    key = image_url.rsplit("/", 1)[1]
    image = http.get(f"{designs_url}/images/{key}")
    assert image.status_code == 200, f"GET /images/{key}: {image.status_code}"
    assert image.headers["content-type"].startswith("image/png"), image.headers
    assert image.content.startswith(b"\x89PNG"), image.content[:8]
    print(f"\n  generation {gen_id} ready: {image_url} ({len(image.content)} bytes)")

    # Step 4: print this — 201 on creation, 200 + created=false on the repeat
    printed = http.post(f"{designs_url}/generations/{gen_id}/print")
    assert printed.status_code == 201, f"print: {printed.status_code} {printed.text}"
    assert printed.json() == {
        "sku": f"AI-{gen_id}",
        "product_url": f"/shop/product/AI-{gen_id}",
        "created": True,
    }, printed.json()
    again = http.post(f"{designs_url}/generations/{gen_id}/print")
    assert again.status_code == 200, f"repeat print: {again.status_code} {again.text}"
    assert again.json()["created"] is False, again.json()
    assert again.json()["sku"] == f"AI-{gen_id}", again.json()

    # Step 5: the catalog family exists by SKU, is unlisted, and never leaks into the grid
    family_sku = f"AI-{gen_id}"
    product_resp = http.get(f"{catalog_url}/products/{family_sku}")
    assert product_resp.status_code == 200, f"GET /products/{family_sku}: {product_resp.text}"
    product = product_resp.json()
    assert product["listed"] is False, product
    assert product["category"] == "Custom", product
    assert product["image_url"] == image_url, (product["image_url"], image_url)
    variants = {v["sku"]: v for v in product["variants"]}
    assert set(variants) == {f"AI-{gen_id}-{s}" for s in SIZES}, sorted(variants)
    for size in SIZES:
        variant = variants[f"AI-{gen_id}-{size}"]
        assert Decimal(str(variant["price"])) == LADDER[size], (size, variant["price"])
        assert variant["in_stock"] is True, variant
    listed = http.get(f"{catalog_url}/products")
    assert listed.status_code == 200, listed.text
    leaked = [p["sku"] for p in listed.json() if p["sku"].startswith("AI-")]
    assert not leaked, f"Unlisted AI families leaked into GET /products: {leaked}"
    categories = http.get(f"{catalog_url}/categories")
    assert categories.status_code == 200, categories.text
    assert "Custom" not in categories.json(), categories.json()
    print(f"  {family_sku} printed: unlisted, 4 variants on the ladder, hidden from the grid")

    # Step 6: an ordinary order for the A3 variant through the untouched orders service
    variant_sku = f"AI-{gen_id}-{ORDERED_SIZE}"
    order_resp = http.post(
        f"{orders_url}/orders",
        json={
            "customer_email": TEST_CUSTOMER_EMAIL,   # replaced by the JWT sub (the owner)
            "shipping_address": TEST_SHIPPING_ADDRESS,
            "items": [{"sku": variant_sku, "name": "ignored", "quantity": 1, "unit_price": 0.01}],
        },
    )
    assert order_resp.status_code in (200, 201), f"POST /orders: {order_resp.status_code} {order_resp.text}"
    order = order_resp.json()
    order_id = order["id"]
    assert order["status"] == "reserved", order
    assert abs(float(order["total_amount"]) - float(LADDER[ORDERED_SIZE])) < 0.01, order["total_amount"]
    item_name = order["items"][0]["name"]
    assert item_name.startswith("Custom: ") and item_name.endswith(f"({ORDERED_SIZE})"), item_name

    # Step 7: pay — ORDER_PAID hits the outbox; production still drives it past PAID
    pay = http.post(f"{orders_url}/orders/{order_id}/pay")
    assert pay.status_code in (200, 201), f"pay: {pay.status_code} {pay.text}"
    assert pay.json()["status"] == "paid", pay.json()
    observed = wait_for_any_status(http, orders_url, order_id, POST_PRODUCTION_STATES)
    assert observed, f"Order {order_id} never left 'paid' within {POLL_TIMEOUT}s (production path)"
    print(f"  order {order_id} for {variant_sku}: paid -> {observed} through the unchanged pipeline")

    # Step 8: the third ORDER_PAID subscriber — designs stamps purchased_at on its own SKU
    bought = wait_for_purchase(http, designs_url, gen_id)
    assert bought.get("purchased_at"), (
        f"Generation {gen_id} has no purchased_at within {POLL_TIMEOUT}s — "
        f"the outbox did not deliver ORDER_PAID to designs: {bought}"
    )
    assert bought["product_url"] == f"/shop/product/AI-{gen_id}", bought
    print(f"  purchased_at set on generation {gen_id}: {bought['purchased_at']}")

    # Step 9: the style profile sees the purchase (deterministic summariser on fake)
    profile = http.post(f"{designs_url}/me/style-profile/refresh")
    assert profile.status_code == 200, f"refresh: {profile.status_code} {profile.text}"
    prof = profile.json()
    assert prof["purchase_count"] >= 1, prof
    assert prof["prompt_count"] >= 1, prof
    assert prof["stale"] is False, prof
    assert isinstance(prof["summary"], str) and prof["summary"].strip(), prof

    # Step 10: a refused prompt fails with the vendor's reason and no image
    reject = http.post(
        f"{designs_url}/generations",
        json={"prompt": "[reject] anything", "personalise": True},
    )
    assert reject.status_code == 202, f"POST /generations [reject]: {reject.status_code} {reject.text}"
    reject_id = reject.json()["id"]
    failed = wait_for_generation(http, designs_url, reject_id)
    assert failed.get("status") == "failed", f"[reject] generation did not fail: {failed}"
    assert failed["failure_reason"] and "rejected" in failed["failure_reason"], failed
    assert failed["image_url"] is None, failed
    history = http.get(f"{designs_url}/generations")
    assert history.status_code == 200, history.text
    ids = [g["id"] for g in history.json()]
    assert reject_id in ids and gen_id in ids, ids
    assert ids[0] == reject_id, f"History is not newest first: {ids[:5]}"
    print(f"  generation {reject_id} refused: {failed['failure_reason']!r}")


def test_studio_routes_require_auth(anon_http, designs_url):
    """Every customer route and the outbox endpoint reject an anonymous caller;
    the health probe stays open."""
    for method, path, body in (
        ("GET", "/generations", None),
        ("POST", "/generations", {"prompt": "anonymous poster attempt"}),
        ("GET", "/saved-prompts", None),
        ("GET", "/me/quota", None),
        ("GET", "/me/style-profile", None),
        ("POST", "/events/order-paid", {
            "event_id": 0, "event_type": "ORDER_PAID", "aggregate_type": "order",
            "aggregate_id": "0", "payload": {},
        }),
    ):
        resp = anon_http.request(method, f"{designs_url}{path}", json=body)
        assert resp.status_code == 401, f"{method} {path}: {resp.status_code} {resp.text[:200]}"
    assert anon_http.get(f"{designs_url}/healthz").status_code == 200


def test_saved_prompts_roundtrip(http, designs_url):
    """Saved prompts (memory tier 1): create -> listed -> delete 204 -> gone."""
    created = http.post(
        f"{designs_url}/saved-prompts",
        json={"title": "Integration round trip", "prompt": "a saved prompt for the round trip"},
    )
    assert created.status_code == 201, f"POST /saved-prompts: {created.status_code} {created.text}"
    saved_id = created.json()["id"]

    listed = http.get(f"{designs_url}/saved-prompts")
    assert listed.status_code == 200, listed.text
    assert saved_id in [s["id"] for s in listed.json()], listed.json()

    deleted = http.delete(f"{designs_url}/saved-prompts/{saved_id}")
    assert deleted.status_code == 204, f"DELETE: {deleted.status_code} {deleted.text}"
    assert deleted.content == b"", deleted.content

    after = http.get(f"{designs_url}/saved-prompts")
    assert after.status_code == 200, after.text
    assert saved_id not in [s["id"] for s in after.json()], after.json()
