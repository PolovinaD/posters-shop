"""
Integration test: the committed OrderEscrow artifact on a real EVM.

Requires the compose stack (make dev / docker compose up -d) WITH the `ganache`
service: the test talks to Ganache directly at localhost:8545 and needs none of
the FastAPI services. It deploys services/payments/contracts/OrderEscrow.json --
the exact bytecode payments deploys per order -- from Ganache's unlocked
account[0] and walks every rule of the contract:

  * all nine require() strings, each asserted verbatim
  * the 80 % / 20 % payout on confirmDelivery, to the wei, with the owner's
    delta corrected for the gas the release transaction cost
  * the refund on cancel (customer is out only the gas of their own pay())
  * the closed-contract lockout ("Order closed." for everyone, even non-owners)

Run with:
    pytest tests/integration/test_escrow_contract_chain.py -v
"""
import json
import pathlib

import pytest
from web3 import Web3
from web3.exceptions import ContractLogicError

ARTIFACT_PATH = pathlib.Path(__file__).parents[2] / "services/payments/contracts/OrderEscrow.json"

CHAIN_ID = 1337
PRICE = 10**16                       # 0.01 ETH: every share below divides exactly
ORDER_ID = 4242
COURIER_SHARE_BPS = 2000
ZERO_ADDRESS = "0x" + "00" * 20

# Solidity `enum State { AwaitingPayment, Funded, InDelivery, Complete, Cancelled }`
AWAITING_PAYMENT, FUNDED, IN_DELIVERY, COMPLETE, CANCELLED = range(5)


def _artifact() -> dict:
    with open(ARTIFACT_PATH) as f:
        return json.load(f)


def expect_revert(reason: str, fn, **tx):
    """`fn` (a bound contract function) must revert with exactly `reason`.

    Ganache phrases it as "VM Exception while processing transaction: revert
    <reason>" and web3 prefixes "execution reverted: "; the bare string must be
    in there. The trailing period is part of every locked message, so the
    assertion catches a contract that drops it.
    """
    with pytest.raises(ContractLogicError) as excinfo:
        fn.transact(tx)
    assert reason in str(excinfo.value), (
        f"expected revert reason {reason!r}, got: {excinfo.value}"
    )


def gas_cost(receipt) -> int:
    return receipt["gasUsed"] * receipt["effectiveGasPrice"]


def test_contract_rules_on_ganache(ganache_url):
    w3 = Web3(Web3.HTTPProvider(ganache_url))
    if not w3.is_connected():
        pytest.skip(f"Ganache not reachable at {ganache_url} -- start the compose stack with the ganache service")
    assert w3.eth.chain_id == CHAIN_ID
    accounts = list(w3.eth.accounts)
    assert len(accounts) >= 10, f"expected Ganache's 10 deterministic accounts, got {len(accounts)}"
    owner, customer, stranger, courier = accounts[0], accounts[1], accounts[2], accounts[3]

    artifact = _artifact()
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    def deploy(price: int = PRICE):
        tx_hash = factory.constructor(customer, price, ORDER_ID, COURIER_SHARE_BPS).transact({"from": owner})
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1, "deploy reverted"
        contract = w3.eth.contract(address=receipt["contractAddress"], abi=artifact["abi"])
        state, c_owner, c_customer, c_courier, c_price, balance = contract.functions.status().call()
        assert (state, c_owner, c_customer, c_courier, c_price, balance) == (
            AWAITING_PAYMENT, owner, customer, ZERO_ADDRESS, price, 0
        )
        return contract

    def status(contract) -> dict:
        state, c_owner, c_customer, c_courier, c_price, balance = contract.functions.status().call()
        return {"state": state, "owner": c_owner, "customer": c_customer,
                "courier": c_courier, "price": c_price, "balance": balance}

    def send(fn, **tx):
        receipt = w3.eth.wait_for_transaction_receipt(fn.transact(tx))
        assert receipt["status"] == 1
        return receipt

    # ------------------------------------------------------------------
    # Contract 1: the happy path with every guard poked along the way
    # ------------------------------------------------------------------
    escrow = deploy()

    # Before funding
    expect_revert("Invalid customer.", escrow.functions.pay(), **{"from": stranger, "value": PRICE})
    expect_revert("Invalid amount.", escrow.functions.pay(), **{"from": customer, "value": PRICE - 1})
    expect_revert("Transfer not complete.", escrow.functions.assignCourier(courier), **{"from": owner})
    expect_revert("Delivery not complete.", escrow.functions.confirmDelivery(), **{"from": owner})
    assert status(escrow)["state"] == AWAITING_PAYMENT, "a reverted call must not change state"

    # pay(): the one transaction the customer signs
    pay_receipt = send(escrow.functions.pay(), **{"from": customer, "value": PRICE})
    after_pay = status(escrow)
    assert after_pay["state"] == FUNDED
    assert after_pay["balance"] == PRICE
    assert w3.eth.get_balance(escrow.address) == PRICE
    funded_events = escrow.events.Funded().process_receipt(pay_receipt)
    assert len(funded_events) == 1
    assert funded_events[0]["args"]["customer"] == customer
    assert funded_events[0]["args"]["amount"] == PRICE

    # Funded: no second payment, courier must be a real address bound by the owner
    expect_revert("Transfer already complete.", escrow.functions.pay(), **{"from": customer, "value": PRICE})
    expect_revert("Invalid address.", escrow.functions.assignCourier(ZERO_ADDRESS), **{"from": owner})
    expect_revert("Only owner.", escrow.functions.assignCourier(courier), **{"from": customer})
    expect_revert("Delivery not complete.", escrow.functions.confirmDelivery(), **{"from": owner})

    assign_receipt = send(escrow.functions.assignCourier(courier), **{"from": owner})
    after_assign = status(escrow)
    assert after_assign["state"] == IN_DELIVERY
    assert after_assign["courier"] == courier
    assigned_events = escrow.events.CourierAssigned().process_receipt(assign_receipt)
    assert len(assigned_events) == 1 and assigned_events[0]["args"]["courier"] == courier

    # In delivery: no cancel, no re-binding, release is owner-only
    expect_revert("Cannot cancel.", escrow.functions.cancel(), **{"from": owner})
    expect_revert("Transfer not complete.", escrow.functions.assignCourier(stranger), **{"from": owner})
    expect_revert("Only owner.", escrow.functions.confirmDelivery(), **{"from": customer})

    # confirmDelivery(): the 80/20 split, to the wei
    courier_amount = PRICE * COURIER_SHARE_BPS // 10000
    owner_amount = PRICE * (10000 - COURIER_SHARE_BPS) // 10000
    assert courier_amount + owner_amount == PRICE

    courier_before = w3.eth.get_balance(courier)
    owner_before = w3.eth.get_balance(owner)
    release_receipt = send(escrow.functions.confirmDelivery(), **{"from": owner})
    courier_after = w3.eth.get_balance(courier)
    owner_after = w3.eth.get_balance(owner)

    after_release = status(escrow)
    assert after_release["state"] == COMPLETE
    assert after_release["balance"] == 0
    assert w3.eth.get_balance(escrow.address) == 0
    completed_events = escrow.events.Completed().process_receipt(release_receipt)
    assert len(completed_events) == 1
    assert completed_events[0]["args"]["ownerAmount"] == owner_amount
    assert completed_events[0]["args"]["courierAmount"] == courier_amount
    # The courier signed nothing, so their delta is the share exactly.
    assert courier_after - courier_before == courier_amount
    # The owner paid the release gas out of the same account.
    assert owner_after - owner_before == owner_amount - gas_cost(release_receipt)

    # Complete: closed to everyone -- `open` runs before `onlyOwner`, so even a
    # non-owner is told "Order closed." rather than "Only owner."
    expect_revert("Order closed.", escrow.functions.pay(), **{"from": customer, "value": PRICE})
    expect_revert("Order closed.", escrow.functions.assignCourier(courier), **{"from": owner})
    expect_revert("Order closed.", escrow.functions.confirmDelivery(), **{"from": owner})
    expect_revert("Order closed.", escrow.functions.cancel(), **{"from": owner})
    expect_revert("Order closed.", escrow.functions.assignCourier(courier), **{"from": customer})

    # ------------------------------------------------------------------
    # Contract 2: funded, then cancelled -> the customer gets the price back
    # ------------------------------------------------------------------
    refundable = deploy()
    expect_revert("Only owner.", refundable.functions.cancel(), **{"from": customer})
    customer_before = w3.eth.get_balance(customer)
    pay_receipt = send(refundable.functions.pay(), **{"from": customer, "value": PRICE})
    assert w3.eth.get_balance(refundable.address) == PRICE

    cancel_receipt = send(refundable.functions.cancel(), **{"from": owner})
    assert status(refundable)["state"] == CANCELLED
    assert w3.eth.get_balance(refundable.address) == 0
    cancelled_events = refundable.events.Cancelled().process_receipt(cancel_receipt)
    assert len(cancelled_events) == 1 and cancelled_events[0]["args"]["refunded"] == PRICE
    # Net: paid PRICE, got PRICE back; only the gas of the customer's own pay() is gone.
    assert w3.eth.get_balance(customer) == customer_before - gas_cost(pay_receipt)
    expect_revert("Order closed.", refundable.functions.pay(), **{"from": customer, "value": PRICE})

    # ------------------------------------------------------------------
    # Contract 3: cancelled while nothing was ever paid -> nothing to refund
    # ------------------------------------------------------------------
    unfunded = deploy()
    cancel_receipt = send(unfunded.functions.cancel(), **{"from": owner})
    assert status(unfunded)["state"] == CANCELLED
    cancelled_events = unfunded.events.Cancelled().process_receipt(cancel_receipt)
    assert len(cancelled_events) == 1 and cancelled_events[0]["args"]["refunded"] == 0
    expect_revert("Order closed.", unfunded.functions.pay(), **{"from": customer, "value": PRICE})

    print(
        f"\n  OrderEscrow verified on Ganache: {escrow.address} released {PRICE} wei"
        f" -> owner {owner_amount} / courier {courier_amount}"
    )
