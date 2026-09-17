"""
Integration test: an escrow order from checkout to the on-chain payout.

Requires the whole compose stack (make dev / docker compose up -d) INCLUDING the
`ganache` service. This is the only place the Solidity contract, web3.py in
payments, the orders escrow endpoints, logistics' courier hand-off and the
outbox all meet on a real EVM.

Flow (the browser path, without a browser):
  create (escrow + wallet) -> POST /escrow deploys the contract -> the customer
  signs pay() with demo account[1]'s key -> POST /escrow/verify marks PAID ->
  outbox -> production -> shipped -> courier pick-up with an explicit
  courier_wallet (demo account[3], NOT the compose default) binds the courier
  on chain -> delivered -> POST /escrow/confirm-delivery releases the funds.

Assertions on chain: the courier is richer by exactly 20 % of amount_wei, the
owner by 80 % minus the gas of the release transaction, the contract is empty.
A second test funds an escrow and cancels the order: the customer gets the
price back and is out only the gas of their own pay().

Run with:
    pytest tests/integration/test_escrow_flow.py -v -s
"""
import re
import time
from decimal import ROUND_HALF_UP, Decimal

import httpx
import pytest
from web3 import Web3

from tests.integration.test_order_flow import (
    POLL_INTERVAL,
    POLL_TIMEOUT,
    TEST_CUSTOMER_EMAIL,
    TEST_SHIPPING_ADDRESS,
    wait_for_any_status,
)

CHAIN_ID = 1337
COURIER_SHARE_BPS = 2000
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Demo account indexes. [1] is the customer (the IEP "pay from the second
# account" convention). [3] is the courier ON PURPOSE: compose sets
# LOGISTICS_DEFAULT_COURIER_WALLET to account[2], so a test binding [2] could
# not tell the explicit wallet apart from the default one.
CUSTOMER_INDEX = 1
COURIER_INDEX = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fund_invoice(w3: Web3, invoice: dict, account: dict):
    """Sign and send the pay() invoice from `account` the way the browser does.

    Builds the transaction from what POST /orders/{id}/escrow returned (to,
    value, data, chain_id), fills nonce/gas/gasPrice, signs with the demo key
    and waits for the receipt. Returns the receipt (status must be 1).
    """
    sender = Web3.to_checksum_address(account["address"])
    tx = {
        "from": sender,
        "to": Web3.to_checksum_address(invoice["to"]),
        "value": int(invoice["value"]),
        "data": invoice["data"],
        "nonce": w3.eth.get_transaction_count(sender),
        "chainId": CHAIN_ID,
    }
    tx["gas"] = w3.eth.estimate_gas(tx)
    tx["gasPrice"] = w3.eth.gas_price
    signed = w3.eth.account.sign_transaction(tx, account["private_key"])
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
    assert receipt["status"] == 1, f"pay() transaction reverted: {receipt}"
    return receipt


def gas_cost(receipt) -> int:
    return receipt["gasUsed"] * receipt["effectiveGasPrice"]


def balance(w3: Web3, address: str) -> int:
    return w3.eth.get_balance(Web3.to_checksum_address(address))


def wait_for_escrow_status(client: httpx.Client, orders_url: str, order_id: int,
                           targets: tuple[str, ...]) -> dict | None:
    """Poll GET /orders/{id}/escrow until escrow_status is in `targets`."""
    deadline = time.monotonic() + POLL_TIMEOUT
    while time.monotonic() < deadline:
        resp = client.get(f"{orders_url}/orders/{order_id}/escrow")
        if resp.status_code == 200 and resp.json().get("escrow_status") in targets:
            return resp.json()
        time.sleep(POLL_INTERVAL)
    return None


def escrow_config(http: httpx.Client, payments_url: str) -> dict:
    resp = http.get(f"{payments_url}/v1/escrow/config")
    assert resp.status_code == 200, f"escrow config failed: {resp.status_code} {resp.text}"
    config = resp.json()
    if not config.get("enabled"):
        pytest.fail(f"escrow disabled -- is ganache up? config={config}")
    assert config["chain_id"] == CHAIN_ID
    assert config["courier_share_bps"] == COURIER_SHARE_BPS
    return config


def demo_accounts(http: httpx.Client, payments_url: str) -> list[dict]:
    resp = http.get(f"{payments_url}/v1/escrow/demo-accounts")
    assert resp.status_code == 200, f"demo accounts failed: {resp.status_code} {resp.text}"
    accounts = resp.json()
    assert len(accounts) >= 4, f"expected Ganache's deterministic accounts, got {accounts}"
    return accounts


def pick_items(http: httpx.Client, catalog_url: str, inventory_url: str) -> tuple[list[dict], Decimal]:
    """Seed (idempotent) and pick one poster variant plus a matching frame, like test_order_flow."""
    for url in (f"{catalog_url}/seed", f"{inventory_url}/seed"):
        seed = http.post(url)
        assert seed.status_code in (200, 201), f"seed failed at {url}: {seed.status_code} {seed.text}"

    products_resp = http.get(f"{catalog_url}/products")
    assert products_resp.status_code == 200, f"Could not list products: {products_resp.text}"
    products = products_resp.json()
    assert products, "Catalog seed produced no products"
    product = products[0]
    variants = [v for v in product.get("variants", []) if v.get("in_stock")]
    assert variants, f"Family {product['sku']} has no variant in stock: {product}"
    variant = variants[0]

    frames_resp = http.get(f"{catalog_url}/frames", params={"size": variant["size"]})
    assert frames_resp.status_code == 200, f"Could not list frames: {frames_resp.text}"
    frame_variants = [
        fv for frame in frames_resp.json() for fv in frame.get("variants", []) if fv.get("in_stock")
    ]
    assert frame_variants, f"No frame in stock for size {variant['size']}"
    frame = frame_variants[0]

    items = [
        {"sku": variant["sku"], "name": "ignored", "quantity": 1, "unit_price": 0.01},
        {"sku": frame["sku"], "name": "ignored", "quantity": 1, "unit_price": 0.01},
    ]
    expected_total = Decimal(str(variant["price"])) + Decimal(str(frame["price"]))
    return items, expected_total


def create_escrow_order(http: httpx.Client, orders_url: str, items: list[dict], customer: dict) -> dict:
    payload = {
        "customer_email": TEST_CUSTOMER_EMAIL,
        "shipping_address": TEST_SHIPPING_ADDRESS,
        "items": items,
        "payment_method": "escrow",
        "customer_wallet": customer["address"],
    }
    resp = http.post(f"{orders_url}/orders", json=payload)
    assert resp.status_code in (200, 201), f"Order creation failed: {resp.status_code} {resp.text}"
    order = resp.json()
    assert order["status"] == "reserved", f"expected reserved, got {order['status']}"
    assert order["payment_method"] == "escrow"
    assert order["escrow_status"] == "awaiting_payment"
    assert order["customer_wallet"].lower() == customer["address"].lower()
    return order


def deploy_escrow(http: httpx.Client, orders_url: str, order: dict, wei_per_usd: int) -> dict:
    resp = http.post(f"{orders_url}/orders/{order['id']}/escrow")
    assert resp.status_code == 200, f"escrow deploy failed: {resp.status_code} {resp.text}"
    escrow = resp.json()
    assert ADDRESS_RE.match(escrow["contract_address"]), escrow
    expected_wei = int(
        (Decimal(str(order["total_amount"])) * wei_per_usd).to_integral_value(rounding=ROUND_HALF_UP)
    )
    assert escrow["amount_wei"] == str(expected_wei), (
        f"amount_wei {escrow['amount_wei']} != {expected_wei} for total {order['total_amount']}"
    )
    invoice = escrow["invoice"]
    assert invoice["to"].lower() == escrow["contract_address"].lower()
    assert invoice["value"] == escrow["amount_wei"]
    assert invoice["chain_id"] == CHAIN_ID
    return escrow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_escrow_order_flow(http, catalog_url, inventory_url, orders_url, logistics_url,
                                payments_url, ganache_url):
    """
    create (escrow) -> deploy -> fund from demo account[1] -> verify -> PAID ->
    outbox -> production -> shipped -> pick-up with courier_wallet (account[3])
    -> in_delivery -> delivered -> confirm-delivery -> released, 80 % / 20 %
    observed on chain.
    """
    # 1-2. Escrow must be on; the demo accounts stand in for the browser's key field
    config = escrow_config(http, payments_url)
    accounts = demo_accounts(http, payments_url)
    customer = accounts[CUSTOMER_INDEX]
    courier = accounts[COURIER_INDEX]
    assert customer["index"] == CUSTOMER_INDEX and courier["index"] == COURIER_INDEX
    w3 = Web3(Web3.HTTPProvider(ganache_url))
    assert w3.is_connected(), f"Ganache not reachable at {ganache_url}"

    # 3. Create the escrow order
    items, expected_total = pick_items(http, catalog_url, inventory_url)
    order = create_escrow_order(http, orders_url, items, customer)
    order_id = order["id"]
    assert Decimal(str(order["total_amount"])) == expected_total, (
        f"Order total {order['total_amount']} is not the catalog total {expected_total}"
    )

    # 4. Deploy the per-order contract (idempotent)
    escrow = deploy_escrow(http, orders_url, order, config["wei_per_usd"])
    contract_address = escrow["contract_address"]
    amount_wei = int(escrow["amount_wei"])
    again = http.post(f"{orders_url}/orders/{order_id}/escrow")
    assert again.status_code == 200 and again.json()["contract_address"] == contract_address, (
        "second POST /escrow must return the same contract, not deploy a new one"
    )

    # 5. Verifying an unfunded escrow changes nothing
    unfunded = http.post(f"{orders_url}/orders/{order_id}/escrow/verify")
    assert unfunded.status_code == 200, unfunded.text
    assert unfunded.json()["status"] == "awaiting_payment", unfunded.json()
    assert http.get(f"{orders_url}/orders/{order_id}").json()["status"] == "reserved"

    # 6. Fund it: the customer's single signed transaction
    pay_receipt = fund_invoice(w3, escrow["invoice"], customer)
    assert balance(w3, contract_address) == amount_wei

    # 7. Verify -> PAID through the same mark_order_paid the Stripe webhook uses.
    # The 15 s reconciler may have seen the funding first; both answers are right.
    verified = http.post(f"{orders_url}/orders/{order_id}/escrow/verify")
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] in ("paid", "already_paid"), verified.json()
    if verified.json()["status"] == "paid":
        assert verified.json()["order_status"] == "paid"
    after_verify = http.get(f"{orders_url}/orders/{order_id}").json()
    # The outbox worker (2 s poll) may already have moved the order past PAID.
    assert after_verify["status"] in ("paid", "producing", "shipped", "delivered"), after_verify
    assert after_verify["escrow_status"] == "funded", after_verify
    repeat = http.post(f"{orders_url}/orders/{order_id}/escrow/verify")
    assert repeat.status_code == 200 and repeat.json()["status"] == "already_paid", repeat.json()

    # 8. Outbox -> production -> logistics: the shipment exists once shipped
    shipped = wait_for_any_status(http, orders_url, order_id, ("shipped", "delivered"))
    assert shipped, f"Order {order_id} never reached 'shipped' within {POLL_TIMEOUT}s"
    shipment_resp = http.get(f"{logistics_url}/shipments/order/{order_id}")
    assert shipment_resp.status_code == 200, f"No shipment for order {order_id}: {shipment_resp.text}"
    shipment = shipment_resp.json()
    shipment_id = shipment["id"]
    assert shipment["status"] == "dispatched", shipment

    # 9. The courier never signs anything: this read can happen any time before the release
    courier_before = balance(w3, courier["address"])

    # Nobody can release a funded-but-unbound escrow -- and the contract's bare
    # reason must survive the trip through payments (Ganache phrases reverts as
    # "VM Exception while processing transaction: revert <reason>").
    early_release = http.post(f"{payments_url}/v1/escrow/{contract_address}/release")
    assert early_release.status_code == 409, early_release.text
    assert early_release.json()["detail"] == "Delivery not complete.", early_release.json()

    # 10. Courier pick-up with an explicit wallet; the binding runs after the response
    pickup = http.put(
        f"{logistics_url}/shipments/{shipment_id}/status",
        json={"status": "in_transit", "courier_wallet": courier["address"]},
    )
    assert pickup.status_code == 200, f"pick-up failed: {pickup.status_code} {pickup.text}"
    in_delivery = wait_for_escrow_status(http, orders_url, order_id, ("in_delivery",))
    assert in_delivery, f"order {order_id} never reached escrow_status in_delivery within {POLL_TIMEOUT}s"
    assert in_delivery["courier_wallet"].lower() == courier["address"].lower(), in_delivery
    chain = in_delivery["chain"]
    assert chain["state"] == "in_delivery", chain
    assert chain["courier"].lower() == courier["address"].lower(), (
        "the explicit courier_wallet must be the one bound on chain, not LOGISTICS_DEFAULT_COURIER_WALLET"
    )

    # 11. Confirming receipt before delivery is refused by orders
    too_early = http.post(f"{orders_url}/orders/{order_id}/escrow/confirm-delivery")
    assert too_early.status_code == 400, f"expected 400 before delivery, got {too_early.status_code} {too_early.text}"

    # 12. Delivered (logistics notifies orders in a background task)
    delivered = http.put(f"{logistics_url}/shipments/{shipment_id}/status", json={"status": "delivered"})
    assert delivered.status_code == 200, f"deliver failed: {delivered.status_code} {delivered.text}"
    assert wait_for_any_status(http, orders_url, order_id, ("delivered",)), (
        f"Order {order_id} never reached 'delivered' within {POLL_TIMEOUT}s"
    )

    # 13. Release. owner_before is read HERE -- after step 10 observed in_delivery
    # (the owner key signed assignCourier and paid its gas) and right before the
    # release, so confirmDelivery is the only owner-signed tx between the reads.
    owner_before = balance(w3, config["owner_address"])
    released = http.post(f"{orders_url}/orders/{order_id}/escrow/confirm-delivery")
    assert released.status_code == 200, f"confirm-delivery failed: {released.status_code} {released.text}"
    assert released.json()["status"] == "released", released.json()
    tx_hash = released.json()["tx_hash"]
    assert tx_hash and tx_hash.startswith("0x"), released.json()
    owner_after = balance(w3, config["owner_address"])
    courier_after = balance(w3, courier["address"])

    final_escrow = http.get(f"{orders_url}/orders/{order_id}/escrow").json()
    assert final_escrow["escrow_status"] == "released", final_escrow
    assert final_escrow["chain"]["state"] == "released", final_escrow["chain"]
    assert final_escrow["chain"]["balance_wei"] == "0", final_escrow["chain"]
    assert balance(w3, contract_address) == 0

    # 14. The payout, to the wei -- computed the way OrderEscrow.confirmDelivery does
    # (config["courier_share_bps"] == 2000 was asserted in step 1).
    courier_amount = amount_wei * 2000 // 10000
    owner_amount = amount_wei - courier_amount
    release_receipt = w3.eth.get_transaction_receipt(tx_hash)
    assert release_receipt["status"] == 1
    assert release_receipt["to"].lower() == contract_address.lower()
    assert courier_after - courier_before == courier_amount, (
        f"courier delta {courier_after - courier_before} != 20 % share {courier_amount}"
    )
    assert owner_after - owner_before == owner_amount - gas_cost(release_receipt), (
        f"owner delta {owner_after - owner_before} != 80 % share {owner_amount} minus release gas {gas_cost(release_receipt)}"
    )
    assert (courier_after - courier_before) + (owner_after - owner_before) + gas_cost(release_receipt) == amount_wei

    # 15. Idempotent release; a delivered order still cannot be cancelled; the
    # contract is closed to everyone, and says so in the contract's own words.
    repeat_release = http.post(f"{orders_url}/orders/{order_id}/escrow/confirm-delivery")
    assert repeat_release.status_code == 200 and repeat_release.json()["status"] == "already_released", repeat_release.json()
    cancel = http.post(f"{orders_url}/orders/{order_id}/cancel")
    assert cancel.status_code == 400, f"a delivered order must not be cancellable: {cancel.status_code} {cancel.text}"
    closed = http.post(f"{payments_url}/v1/escrow/{contract_address}/cancel")
    assert closed.status_code == 409, closed.text
    assert closed.json()["detail"] == "Order closed.", closed.json()

    print(
        f"\n  escrow path confirmed: order {order_id} contract {contract_address}"
        f" released {amount_wei} wei -> owner 80 % / courier 20 %"
        f" (pay gas {gas_cost(pay_receipt)}, release gas {gas_cost(release_receipt)})"
    )


def test_escrow_cancel_refunds_customer(http, catalog_url, inventory_url, orders_url,
                                        payments_url, ganache_url):
    """A funded escrow order that is cancelled refunds the customer the exact price."""
    config = escrow_config(http, payments_url)
    customer = demo_accounts(http, payments_url)[CUSTOMER_INDEX]
    w3 = Web3(Web3.HTTPProvider(ganache_url))
    assert w3.is_connected(), f"Ganache not reachable at {ganache_url}"

    items, _ = pick_items(http, catalog_url, inventory_url)
    order = create_escrow_order(http, orders_url, items, customer)
    order_id = order["id"]
    escrow = deploy_escrow(http, orders_url, order, config["wei_per_usd"])
    contract_address = escrow["contract_address"]
    amount_wei = int(escrow["amount_wei"])

    customer_before = balance(w3, customer["address"])
    pay_receipt = fund_invoice(w3, escrow["invoice"], customer)
    assert balance(w3, contract_address) == amount_wei
    assert balance(w3, customer["address"]) == customer_before - amount_wei - gas_cost(pay_receipt)

    # Cancel refunds on chain BEFORE the row flips. No assertion on released_stock:
    # the reconciler may already have marked the order paid (stock committed), in
    # which case the cancel path commits no release -- the refund is what matters.
    cancel = http.post(f"{orders_url}/orders/{order_id}/cancel")
    assert cancel.status_code == 200, f"cancel failed: {cancel.status_code} {cancel.text}"
    assert cancel.json()["status"] == "cancelled", cancel.json()

    state = http.get(f"{orders_url}/orders/{order_id}/escrow").json()
    assert state["escrow_status"] == "cancelled", state
    assert state["chain"]["state"] == "cancelled", state["chain"]
    assert state["chain"]["balance_wei"] == "0", state["chain"]
    assert balance(w3, contract_address) == 0
    # The refund returned exactly the price: the customer is out only their own pay() gas.
    assert balance(w3, customer["address"]) == customer_before - gas_cost(pay_receipt), (
        f"customer delta {balance(w3, customer['address']) - customer_before} != -{gas_cost(pay_receipt)} (pay gas)"
    )
    assert http.get(f"{orders_url}/orders/{order_id}").json()["status"] == "cancelled"

    print(f"\n  escrow refund confirmed: order {order_id} contract {contract_address} refunded {amount_wei} wei")
